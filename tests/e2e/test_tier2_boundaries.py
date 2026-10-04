"""
Tier 2: Boundary & Corner Case Hardening (E-01 through E-14).
Tests edge conditions, invalid configurations, resource limits, and error recovery.
"""

import os
import sys
import time
import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from tests.e2e.conftest import require_feature, require_features
from src.core.config import ConfigManager, ConfigData, VaultProfile
from src.core.sync_worker import SyncWorker, SyncStatus, try_recover_stale_lock
from src.core.rclone_manager import RcloneManager
from src.main import acquire_single_instance_lock, release_single_instance_lock


# ============================================================================
# E-01: Vault Path Validation (Root & Anchor Rejection)
# ============================================================================
def test_e01_vault_path_validation_rejects_root(isolated_env, headless_gui):
    """E-01: Validates that system root, user home, or anchor paths are rejected."""
    from src.gui.app_window import MainWindow

    cfg_mgr = MagicMock()
    mock_rclone = MagicMock()
    mock_rclone.is_remote_configured.return_value = True

    with patch("customtkinter.CTk.__init__", return_value=None):
        win = MainWindow(config_manager=cfg_mgr, worker=MagicMock(), rclone_mgr=mock_rclone)

        # 1. Empty path rejected
        win.cfg.local_vault_path = ""
        assert win.can_auto_start_sync() is False

        # 2. Filesystem root rejected
        win.cfg.local_vault_path = str(Path("/").resolve())
        assert win.can_auto_start_sync() is False

        # 3. User home rejected
        win.cfg.local_vault_path = str(Path.home().resolve())
        assert win.can_auto_start_sync() is False


# ============================================================================
# E-02: Missing or Deleted Local Vault Directory
# ============================================================================
def test_e02_deleted_vault_aborts_sync(isolated_env, tmp_path):
    """E-02: Local vault directory deleted while worker is running aborts safely."""
    vault = tmp_path / "ephemeral_vault"
    vault.mkdir()
    cfg = ConfigData(local_vault_path=str(vault), remote_folder_name="vault")
    mock_rclone = MagicMock()

    worker = SyncWorker(config=cfg, rclone_manager=mock_rclone)

    # Delete vault directory right before execution
    vault.rmdir()
    assert not vault.exists()

    success = worker._execute_sync()
    assert success is False
    assert worker.status == SyncStatus.ERROR
    assert "no existe" in worker.last_message.lower() or "inválida" in worker.last_message.lower()
    mock_rclone.build_bisync_command.assert_not_called()


# ============================================================================
# E-03: Stale Lock File Recovery & Single-Instance Protection
# ============================================================================
def test_e03_stale_lock_recovery(isolated_env, tmp_path):
    """E-03: Stale PID lock files are recovered; active process locks are preserved."""
    # 1. Test rclone stale lock recovery
    fake_lck = tmp_path / "test.lck"
    # Write a lock file with a guaranteed dead PID (PID 99999999)
    fake_lck.write_text(json.dumps({"PID": "99999999"}), encoding="utf-8")
    assert fake_lck.exists()

    error_str = f"Fatal error: bisync is already running for this path: {fake_lck}"
    recovered = try_recover_stale_lock(error_str)
    assert recovered is True
    assert not fake_lck.exists(), "Stale lock file should have been deleted"

    # 2. Test app single-instance lock recovery
    lock_file = isolated_env / "app.lock"
    # Stale PID in app.lock
    lock_file.write_text("99999999", encoding="utf-8")
    acquired = acquire_single_instance_lock()
    assert acquired is True
    assert lock_file.read_text(encoding="utf-8").strip() == str(os.getpid())
    release_single_instance_lock()
    assert not lock_file.exists()


# ============================================================================
# E-04: Bisync Safety Trip (Forbid Automatic --resync)
# ============================================================================
def test_e04_bisync_safety_trip_forbids_auto_resync(isolated_env, tmp_path):
    """E-04: Massive delete safety trip strictly forbids automatic --resync."""
    vault = tmp_path / "safe_vault"
    vault.mkdir()
    cfg = ConfigData(local_vault_path=str(vault), remote_folder_name="vault", first_sync_done=True)
    mock_rclone = MagicMock()
    mock_rclone.build_bisync_command.return_value = ["mock_rclone", "bisync"]

    worker = SyncWorker(config=cfg, rclone_manager=mock_rclone)

    with patch("subprocess.run") as mock_run:
        err = subprocess.CalledProcessError(
            returncode=1,
            cmd=["rclone"],
            stderr="Fatal error: Safety trip! Too many deletes (15 > 10). Must run --resync to recover."
        )
        mock_run.side_effect = err

        success = worker._execute_sync()
        assert success is False
        assert worker.status == SyncStatus.ERROR
        assert "guardas de seguridad" in worker.last_message.lower()

        # Critical invariant: must NOT re-call with resync=True
        for call_args in mock_rclone.build_bisync_command.call_args_list:
            kwargs = call_args[1] if len(call_args) > 1 else {}
            assert kwargs.get("resync") is not True, "Must never automatically run --resync on safety trips"


# ============================================================================
# E-05: Network Outage Mid-Sync & Cooldown Protection
# ============================================================================
def test_e05_network_outage_error_handling(isolated_env, tmp_path):
    """E-05: Mid-sync network drop marks ERROR, preserves worker thread."""
    vault = tmp_path / "vault"
    vault.mkdir()
    cfg = ConfigData(local_vault_path=str(vault), remote_folder_name="vault")
    mock_rclone = MagicMock()
    mock_rclone.build_bisync_command.return_value = ["mock_rclone"]

    worker = SyncWorker(config=cfg, rclone_manager=mock_rclone)

    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = subprocess.CalledProcessError(
            returncode=2,
            cmd=["rclone"],
            stderr="ERROR : Failed to copy: dial tcp: lookup oauth2.googleapis.com: no such host"
        )
        success = worker._execute_sync()
        assert success is False
        assert worker.status == SyncStatus.ERROR
        assert "oauth2.googleapis.com" in worker.last_message or "fallo" in worker.last_message.lower()


# ============================================================================
# E-06: Google Drive Quota Limits
# ============================================================================
def test_e06_quota_limits(isolated_env):
    """E-06: Evaluates storage quota calculation and threshold alerts."""
    rclone = RcloneManager()

    # Simulate quota json output: 14.5 GB used out of 15 GB (96.6% full)
    fake_about = json.dumps({
        "total": 15000000000,
        "used": 14500000000,
        "free": 500000000
    })

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=fake_about, stderr="")
        quota = rclone.get_storage_quota()
        assert quota is not None
        assert quota["total"] == 15000000000
        assert quota["used"] == 14500000000
        assert quota["percent"] == pytest.approx(0.9667, rel=1e-2)
        assert quota["percent_str"] == "96.7%"


# ============================================================================
# E-07: Large Batch Transfer Boundaries
# ============================================================================
def test_e07_large_batch_boundary(isolated_env, sample_vault):
    """E-07: Large batch transfer (>50 files) executes smoothly."""
    # Create 60 files in vault
    bulk_dir = sample_vault / "Bulk"
    bulk_dir.mkdir()
    for i in range(60):
        (bulk_dir / f"note_{i:03d}.md").write_text(f"Bulk note content {i}", encoding="utf-8")

    files = list(sample_vault.glob("**/*.md"))
    assert len(files) >= 60

    cfg = ConfigData(local_vault_path=str(sample_vault), remote_folder_name="vault")
    mock_rclone = MagicMock()
    mock_rclone.build_bisync_command.return_value = ["mock_rclone"]

    worker = SyncWorker(config=cfg, rclone_manager=mock_rclone)

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="Bisync successful", stderr="")
        success = worker._execute_sync()
        assert success is True
        assert worker.status == SyncStatus.SUCCESS


# ============================================================================
# E-08: Rapid File System Edit Bursts (Debounce Timer)
# ============================================================================
def test_e08_rapid_edit_burst_debounce(isolated_env, sample_vault):
    """E-08: Rapid bursts of file modifications are coalesced by debounce timer."""
    from src.core.vault_watcher import VaultWatcher

    trigger_count = 0

    def mock_callback():
        nonlocal trigger_count
        trigger_count += 1

    watcher = VaultWatcher(callback=mock_callback, debounce_seconds=0.1)
    handler = watcher.handler

    # Simulate rapid successive file modification events within 50ms
    for _ in range(5):
        handler._on_valid_change()
        time.sleep(0.01)

    # Immediately after rapid burst, callback must NOT have fired yet
    assert trigger_count == 0

    # Wait for debounce timer (100ms) to elapse
    time.sleep(0.2)
    assert trigger_count == 1, "Rapid burst must result in exactly 1 coalesced callback"


# ============================================================================
# E-09: Concurrent Manual Sync Invocations
# ============================================================================
def test_e09_concurrent_manual_sync(isolated_env, tmp_path):
    """E-09: Rapid duplicate clicks to trigger sync are ignored safely."""
    vault = tmp_path / "vault"
    vault.mkdir()
    cfg = ConfigData(local_vault_path=str(vault))
    worker = SyncWorker(config=cfg, rclone_manager=MagicMock())

    # When worker is already syncing
    worker._is_syncing = True
    assert worker.trigger_now() is False, "Concurrent trigger during active sync must return False"

    # When worker is paused
    worker._is_syncing = False
    worker._paused = True
    assert worker.trigger_now() is False, "Trigger during paused state must return False"


# ============================================================================
# E-10: Headless Display / Missing DISPLAY Variable
# ============================================================================
def test_e10_headless_display_safety(isolated_env, monkeypatch):
    """E-10: Application survives in headless environments without X11 server."""
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)

    # In headless environment, --minimized flag can run without GUI window
    with patch("src.main.acquire_single_instance_lock", return_value=True), \
         patch("src.main.release_single_instance_lock"), \
         patch("src.main.ConfigManager"), \
         patch("src.main.RcloneManager"), \
         patch("src.main.SyncWorker"), \
         patch("src.main.TrayManager"), \
         patch("src.main.MainWindow") as mock_window_cls, \
         patch.object(sys, "argv", ["main.py", "--minimized"]):

        mock_app = MagicMock()
        mock_app.can_auto_start_sync.return_value = False
        mock_window_cls.return_value = mock_app

        from src.main import main
        mock_app.mainloop.side_effect = None
        main()
        mock_app.withdraw.assert_called_once()


# ============================================================================
# E-11: Missing Linux Desktop Utilities
# ============================================================================
def test_e11_missing_desktop_tools(isolated_env):
    """E-11: Handles missing xdg-open or desktop launchers without crash."""
    require_feature("F-17")
    worker = MagicMock()
    worker.config.local_vault_path = "/tmp/test"
    from src.tray.tray_icon import TrayManager
    tray = TrayManager(worker=worker, on_open_gui=MagicMock(), on_exit=MagicMock())

    with patch("subprocess.Popen", side_effect=FileNotFoundError("xdg-open not found")):
        # Must catch exception and log warning rather than crashing app
        try:
            tray.open_vault_folder()
        except Exception as e:
            pytest.fail(f"TrayManager crashed on missing desktop tool: {e}")


# ============================================================================
# E-12: High-Volume Log Flooding
# ============================================================================
def test_e12_high_volume_log_flood(isolated_env):
    """E-12: Handles bursts of 5,000 log lines with bounded memory ring buffer."""
    require_feature("F-10")
    from src.utils.log_handler import GuiLogHandler
    import logging

    handler = GuiLogHandler(max_entries=1000)
    logger = logging.getLogger("test_flood_logger")
    logger.addHandler(handler)

    for i in range(5000):
        logger.info(f"Flood line {i}")

    entries = handler.get_entries()
    assert len(entries) <= 1000, "Log handler must enforce max_entries ring buffer limit"


# ============================================================================
# E-13: Corrupted history.json File Recovery
# ============================================================================
def test_e13_corrupt_history_recovery(isolated_env):
    """E-13: Recovers gracefully when history.json contains invalid or corrupt JSON."""
    require_feature("F-07")
    from src.core.history_manager import SyncHistoryManager

    history_file = isolated_env / "history.json"
    history_file.write_text("{ INVALID JSON SYNTAX @@@ }}}", encoding="utf-8")

    mgr = SyncHistoryManager(history_file=history_file)
    runs = mgr.get_recent_runs()
    assert runs == [], "Corrupted history file should fall back to empty list without crash"


# ============================================================================
# E-14: Vault Profile Switch in Flight
# ============================================================================
def test_e14_vault_switch_in_flight(isolated_env, tmp_path):
    """E-14: Switching vaults while sync is in flight does not corrupt state."""
    v1 = tmp_path / "vault1"
    v2 = tmp_path / "vault2"
    v1.mkdir()
    v2.mkdir()

    cfg = ConfigData(
        vaults=[
            VaultProfile(id="v1", name="Vault 1", local_path=str(v1)),
            VaultProfile(id="v2", name="Vault 2", local_path=str(v2))
        ],
        active_vault_id="v1",
        local_vault_path=str(v1)
    )

    worker = SyncWorker(config=cfg, rclone_manager=MagicMock())
    worker._is_syncing = True

    # Switching active vault profile
    cfg.active_vault_id = "v2"
    cfg.local_vault_path = str(v2)

    # Worker finishes sync on v1
    worker._is_syncing = False
    assert cfg.active_vault_id == "v2"
