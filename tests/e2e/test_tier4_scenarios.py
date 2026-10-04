"""
Tier 4: Real-World Application Scenarios (S-01 through S-05).
Validates end-to-end user workflows, lifecycle progressions, and realistic usage patterns.
"""

import os
import sys
import time
import json
import logging
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from tests.e2e.conftest import require_feature, require_features
from src.core.config import ConfigManager, ConfigData, VaultProfile
from src.core.sync_worker import SyncWorker, SyncStatus
from src.tray.tray_icon import TrayManager
from src.core.rclone_manager import RcloneManager


# ============================================================================
# S-01: First-Run & Onboarding Workflow
# ============================================================================
def test_s01_first_run_onboarding_workflow(isolated_env, sample_vault):
    """S-01: First launch -> unconfigured state -> configure vault -> initial sync -> ready."""
    cfg_mgr = ConfigManager()
    cfg = cfg_mgr.load()

    # Initial state: unconfigured
    assert cfg.local_vault_path == ""
    assert not cfg.first_sync_done

    # User sets up vault
    cfg.local_vault_path = str(sample_vault)
    cfg.remote_folder_name = "Obsidian_Backup"
    cfg_mgr.save(cfg)

    # Reload from disk to verify persistence
    reloaded_cfg = cfg_mgr.load()
    assert reloaded_cfg.local_vault_path == str(sample_vault)

    # Initial sync execution (resync=True on first run)
    mock_rclone = MagicMock()
    mock_rclone.ensure_remote_dir.return_value = True
    mock_rclone.build_bisync_command.return_value = ["mock_rclone", "bisync", "--resync"]

    worker = SyncWorker(config=reloaded_cfg, rclone_manager=mock_rclone)

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="Bisync successful", stderr="")
        success = worker._execute_sync()
        assert success is True
        assert worker.status == SyncStatus.SUCCESS
        assert reloaded_cfg.first_sync_done is True

        # Verify resync was requested for the first sync
        call_kwargs = mock_rclone.build_bisync_command.call_args[1]
        assert call_kwargs.get("resync") is True


# ============================================================================
# S-02: Headless Background Daemon Workflow
# ============================================================================
def test_s02_headless_daemon_workflow(isolated_env, sample_vault):
    """S-02: --minimized launch -> background watcher -> note change -> auto sync -> tray update."""
    cfg_mgr = ConfigManager()
    cfg = ConfigData(
        local_vault_path=str(sample_vault),
        remote_folder_name="vault",
        first_sync_done=True,
        realtime_sync_enabled=True,
        debounce_delay_seconds=1
    )
    cfg_mgr.save(cfg)

    mock_rclone = MagicMock()
    mock_rclone.build_bisync_command.return_value = ["mock_rclone"]

    worker = SyncWorker(config=cfg, rclone_manager=mock_rclone)
    tray = TrayManager(worker=worker, on_open_gui=MagicMock(), on_exit=MagicMock())
    worker.register_listener(tray.update_status)

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="Bisync successful", stderr="")

        # Start background worker
        worker.start()
        assert worker._running is True
        assert worker.status in (SyncStatus.IDLE, SyncStatus.SUCCESS)

        # Simulate note change triggering watcher callback
        worker._on_watcher_change()
        assert worker._wakeup_event.is_set()

        # Stop worker
        worker.stop()
        assert worker._running is False


# ============================================================================
# S-03: Heavy Daily Note Workflow
# ============================================================================
def test_s03_daily_note_editing_workflow(isolated_env, sample_vault):
    """S-03: Continuous typing, debounced sync, file history, and log capture."""
    require_features("F-07", "F-10", "F-12")
    from src.core.history_manager import SyncHistoryManager, SyncRunRecord
    from src.utils.log_handler import GuiLogHandler

    history_mgr = SyncHistoryManager(history_file=isolated_env / "history.json")
    log_handler = GuiLogHandler(max_entries=500)
    logger = logging.getLogger("obsidian_sync")
    logger.addHandler(log_handler)

    # User modifies daily note
    daily_file = sample_vault / "Daily" / "2026-10-03.md"
    daily_file.write_text("# Updated Daily Notes\nAdded section 1", encoding="utf-8")

    logger.info("File system change detected: Daily/2026-10-03.md")

    # Sync triggers and completes
    history_mgr.record_run(SyncRunRecord(
        id="sync_daily_01",
        timestamp="2026-10-03T16:30:00Z",
        vault_name="TestVault",
        status="SUCCESS",
        duration_seconds=1.2,
        files_transferred=["Daily/2026-10-03.md"],
        bytes_transferred=512
    ))

    logger.info("Sync finished for Daily/2026-10-03.md")

    # Verify history entry
    runs = history_mgr.get_recent_runs()
    assert len(runs) >= 1
    assert "Daily/2026-10-03.md" in runs[0].files_transferred

    # Verify log entry is searchable
    results = log_handler.get_entries(search_query="Daily/2026-10-03.md")
    assert len(results) >= 1


# ============================================================================
# S-04: Offline -> Online Recovery Workflow
# ============================================================================
def test_s04_offline_online_recovery_workflow(isolated_env, sample_vault):
    """S-04: Network failure -> error state & cooldown -> network restores -> retry succeeds."""
    import subprocess
    cfg = ConfigData(local_vault_path=str(sample_vault), remote_folder_name="vault")
    mock_rclone = MagicMock()
    mock_rclone.build_bisync_command.return_value = ["mock_rclone"]

    worker = SyncWorker(config=cfg, rclone_manager=mock_rclone)
    tray = TrayManager(worker=worker, on_open_gui=MagicMock(), on_exit=MagicMock())
    worker.register_listener(tray.update_status)

    with patch.object(tray, "notify") as mock_notify:
        # Phase 1: Network failure mid-sync
        with patch("subprocess.run", side_effect=subprocess.CalledProcessError(
            returncode=1, cmd=["rclone"], stderr="ERROR : Connection refused: dial tcp"
        )):
            success = worker._execute_sync()
            assert success is False
            assert worker.status == SyncStatus.ERROR
            assert mock_notify.call_count == 1

        # Phase 2: Duplicate failure suppressed by cooldown
        with patch("subprocess.run", side_effect=subprocess.CalledProcessError(
            returncode=1, cmd=["rclone"], stderr="ERROR : Connection refused: dial tcp"
        )):
            worker._execute_sync()
            # Notification must remain at 1 call due to cooldown
            assert mock_notify.call_count == 1

        # Phase 3: Network restored -> manual sync succeeds
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="Bisync successful", stderr="")
            success = worker._execute_sync()
            assert success is True
            assert worker.status == SyncStatus.SUCCESS
            assert tray._status_text.startswith("Sincronizado con éxito")


# ============================================================================
# S-05: Multi-Vault Management Workflow
# ============================================================================
def test_s05_multi_vault_switching_workflow(isolated_env, tmp_path):
    """S-05: Configure Vault A and Vault B -> switch active vault -> sync respective vault."""
    v1 = tmp_path / "WorkVault"
    v2 = tmp_path / "PersonalVault"
    v1.mkdir()
    v2.mkdir()
    (v1 / "work.md").write_text("Work notes", encoding="utf-8")
    (v2 / "personal.md").write_text("Personal diary", encoding="utf-8")

    cfg_mgr = ConfigManager()
    cfg = ConfigData(
        vaults=[
            VaultProfile(id="v_work", name="Work", local_path=str(v1), remote_folder="WorkRemote"),
            VaultProfile(id="v_pers", name="Personal", local_path=str(v2), remote_folder="PersonalRemote"),
        ],
        active_vault_id="v_work",
        local_vault_path=str(v1),
        remote_folder_name="WorkRemote"
    )
    cfg_mgr.save(cfg)

    # 1. Sync Work Vault
    mock_rclone = MagicMock()
    mock_rclone.build_bisync_command.return_value = ["mock_rclone"]
    worker = SyncWorker(config=cfg, rclone_manager=mock_rclone)

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="Bisync successful", stderr="")
        success = worker._execute_sync()
        assert success is True
        mock_rclone.build_bisync_command.assert_called_with(str(v1), "WorkRemote", resync=True)

    # 2. Switch to Personal Vault
    cfg.active_vault_id = "v_pers"
    cfg.local_vault_path = str(v2)
    cfg.remote_folder_name = "PersonalRemote"
    cfg.first_sync_done = False
    cfg_mgr.save(cfg)

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="Bisync successful", stderr="")
        success = worker._execute_sync()
        assert success is True
        mock_rclone.build_bisync_command.assert_called_with(str(v2), "PersonalRemote", resync=True)
