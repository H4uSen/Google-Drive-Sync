"""
Tier 3: Cross-Feature Combination Suite (C-01 through C-07).
Validates multi-component integrations, event messaging pipelines, and subsystem interactions.
"""

import os
import sys
import time
import json
import logging
import threading
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from tests.e2e.conftest import require_feature, require_features
from src.core.config import ConfigManager, VaultProfile
from src.core.sync_worker import SyncWorker, SyncStatus
from src.tray.tray_icon import TrayManager
from tests.builders import vault_config


# ============================================================================
# C-01: Full Sync Lifecycle (Worker -> Events -> History -> Logs)
# ============================================================================
def test_c01_full_sync_lifecycle(isolated_env, sample_vault):
    """C-01: Complete sync cycle cascades through events, history, and logging."""
    require_features("F-25", "F-07", "F-10")
    from src.core.events import EventDispatcher, EventType, Event
    from src.core.history_manager import SyncHistoryManager, SyncRunRecord
    from src.utils.log_handler import GuiLogHandler

    # Setup subsystems
    dispatcher = EventDispatcher()
    history_mgr = SyncHistoryManager(history_file=isolated_env / "history.json")
    log_handler = GuiLogHandler(max_entries=500)
    logger = logging.getLogger("obsidian_sync")
    logger.addHandler(log_handler)

    events_received = []
    dispatcher.subscribe(EventType.STATUS_CHANGED, lambda e: events_received.append(e))
    dispatcher.subscribe(EventType.BATCH_COMPLETED, lambda e: events_received.append(e))

    # Simulate sync execution and pipeline cascade
    dispatcher.emit(EventType.STATUS_CHANGED, {"status": "SYNCING", "message": "Iniciando sincronización..."})
    logger.info("Starting sync cycle for vault TestVault")

    record = SyncRunRecord(
        id="sync_c01",
        timestamp="2026-10-03T16:00:00Z",
        vault_name="TestVault",
        status="SUCCESS",
        duration_seconds=2.1,
        files_transferred=["Notes/Welcome.md", "Notes/Project.md"],
        bytes_transferred=4096
    )
    history_mgr.record_run(record)
    dispatcher.emit(EventType.BATCH_COMPLETED, {"total_files": 2, "total_bytes": 4096})
    dispatcher.emit(EventType.STATUS_CHANGED, {"status": "SUCCESS", "message": "Sincronizado con éxito"})
    logger.info("Sync completed successfully")

    # Assertions across subsystems
    assert len(events_received) == 3
    assert events_received[0].data["status"] == "SYNCING"
    assert events_received[-1].data["status"] == "SUCCESS"

    runs = history_mgr.get_recent_runs()
    assert len(runs) == 1
    assert runs[0].id == "sync_c01"
    assert len(runs[0].files_transferred) == 2

    log_entries = log_handler.get_entries()
    assert any("Starting sync cycle" in e.message for e in log_entries)
    assert any("Sync completed successfully" in e.message for e in log_entries)


# ============================================================================
# C-02: Conflict Detection Pipeline (Conflict Line -> Event -> Tray -> History)
# ============================================================================
def test_c02_conflict_detection_pipeline(isolated_env):
    """C-02: Conflict during sync triggers event dispatch, tray alert, and history status."""
    require_features("F-20", "F-25", "F-07")
    from src.core.events import EventDispatcher, EventType
    from src.core.history_manager import SyncHistoryManager, SyncRunRecord

    dispatcher = EventDispatcher()
    history_mgr = SyncHistoryManager(history_file=isolated_env / "history.json")
    worker = MagicMock()
    tray = TrayManager(worker=worker, on_open_gui=MagicMock(), on_exit=MagicMock())

    conflict_alerts = []

    def handle_conflict(event):
        tray.notify_conflict(event.data.get("filename", "unknown"))
        conflict_alerts.append(event.data)

    dispatcher.subscribe(EventType.CONFLICT_DETECTED, handle_conflict)

    with patch.object(tray, "notify") as mock_notify:
        # Simulate rclone bisync detecting conflict
        conflict_file = "Notes/Daily_20261003.conflict1.md"
        dispatcher.emit(EventType.CONFLICT_DETECTED, {
            "filename": conflict_file,
            "details": "Path1 conflict loser"
        })

        assert len(conflict_alerts) == 1
        mock_notify.assert_called_once()
        assert "Conflicto" in mock_notify.call_args[0][0] or "Conflicto" in mock_notify.call_args[0][1]

        # Record in history as conflict status
        history_mgr.record_run(SyncRunRecord(
            id="sync_conflict_01",
            timestamp="2026-10-03T16:15:00Z",
            vault_name="TestVault",
            status="CONFLICT",
            duration_seconds=1.5,
            files_transferred=[conflict_file],
            error_message="Bisync conflict detected"
        ))

        recent = history_mgr.get_recent_runs()
        assert recent[0].status == "CONFLICT"


# ============================================================================
# C-03: Large Batch Notification Pipeline
# ============================================================================
def test_c03_large_batch_notification_pipeline(isolated_env):
    """C-03: Batch sync >5 files emits batch completed event and tray alert."""
    require_features("F-22", "F-25", "F-07")
    from src.core.events import EventDispatcher, EventType
    from src.core.history_manager import SyncHistoryManager, SyncRunRecord

    dispatcher = EventDispatcher()
    history_mgr = SyncHistoryManager(history_file=isolated_env / "history.json")
    tray = TrayManager(worker=MagicMock(), on_open_gui=MagicMock(), on_exit=MagicMock())

    batch_notifications = []

    def on_batch(event):
        files_count = event.data.get("total_files", 0)
        if files_count > 5:
            tray.notify_batch_complete(file_count=files_count, total_bytes=event.data.get("total_bytes", 0))
            batch_notifications.append(event.data)

    dispatcher.subscribe(EventType.BATCH_COMPLETED, on_batch)

    with patch.object(tray, "notify") as mock_notify:
        batch_files = [f"Notes/Note_{i}.md" for i in range(12)]
        dispatcher.emit(EventType.BATCH_COMPLETED, {"total_files": 12, "total_bytes": 1048576})

        assert len(batch_notifications) == 1
        mock_notify.assert_called_once()
        assert "12" in mock_notify.call_args[0][1]


# ============================================================================
# C-04: Tray-to-UI Status Synchronization
# ============================================================================
def test_c04_tray_to_ui_sync(isolated_env, headless_gui):
    """C-04: Tray trigger initiates sync, propagating status updates to GUI."""
    cfg = vault_config(local_path="/tmp/v", remote_folder="v")
    mock_rclone = MagicMock()
    mock_rclone.is_remote_configured.return_value = True
    worker = SyncWorker(config=cfg, rclone_manager=mock_rclone)

    tray = TrayManager(worker=worker, on_open_gui=MagicMock(), on_exit=MagicMock())
    worker.register_listener(tray.update_status)

    from src.gui.app_window import MainWindow
    cfg_mgr = MagicMock()

    with patch("customtkinter.CTk.__init__", return_value=None):
        win = MainWindow(config=cfg, config_manager=cfg_mgr, worker=worker, rclone_mgr=mock_rclone)
        win.status_badge = MagicMock()
        win.log_box = MagicMock()
        win.after = lambda delay, cb: cb()
        worker.register_listener(win.on_worker_status_update)

        # Trigger sync from tray menu
        menu = tray._build_menu()
        sync_item = [item for item in menu if item.text == "Sincronizar Ahora"][0]

        with patch.object(worker, "_execute_sync", return_value=True):
            # Simulate worker notifying SYNCING state
            worker._notify(SyncStatus.SYNCING, "Sincronizando...")
            assert tray._status_text == "Sincronizando..."
            win.status_badge.configure.assert_called_with(
                text="● Sincronizando...",
                text_color=SyncStatus.SYNCING.color
            )


# ============================================================================
# C-05: Tray Pause & File Watcher Coordination
# ============================================================================
def test_c05_tray_pause_watcher_coordination(isolated_env, tmp_path):
    """C-05: Pausing sync from tray suppresses watcher triggers until resumed."""
    vault = tmp_path / "vault"
    vault.mkdir()
    cfg = vault_config(local_path=str(vault), remote_folder="v")
    worker = SyncWorker(config=cfg, rclone_manager=MagicMock())
    tray = TrayManager(worker=worker, on_open_gui=MagicMock(), on_exit=MagicMock())

    assert not worker._paused

    # 1. Tray pause
    tray._toggle_pause()
    assert worker._paused
    assert worker.status == SyncStatus.PAUSED

    # 2. File modification detected during pause
    worker._on_watcher_change()
    # While paused, watcher changes must be ignored / not set wakeup event
    assert not worker._wakeup_event.is_set()

    # 3. Tray resume
    tray._toggle_pause()
    assert not worker._paused
    assert worker.status == SyncStatus.IDLE


# ============================================================================
# C-06: Subprocess Failure Cascading
# ============================================================================
def test_c06_subprocess_failure_cascading(isolated_env, tmp_path):
    """C-06: Subprocess failure is caught by boundary, logged, and notified via tray."""
    vault = tmp_path / "vault"
    vault.mkdir()
    cfg = vault_config(local_path=str(vault), remote_folder="v")
    mock_rclone = MagicMock()
    mock_rclone.ensure_remote_dir.side_effect = subprocess.CalledProcessError(
        returncode=1, cmd=["rclone"], stderr="Fatal error: authentication token revoked"
    )

    worker = SyncWorker(config=cfg, rclone_manager=mock_rclone)
    tray = TrayManager(worker=worker, on_open_gui=MagicMock(), on_exit=MagicMock())
    worker.register_listener(tray.update_status)

    with patch.object(tray, "notify") as mock_notify:
        success = worker._execute_sync()
        assert success is False
        assert worker.status == SyncStatus.ERROR

        # Tray notification should have triggered for the error
        mock_notify.assert_called_once()
        assert "Error" in mock_notify.call_args[0][0]


# ============================================================================
# C-07: Concurrent Log Streaming & Export Consistency
# ============================================================================
def test_c07_concurrent_log_export(isolated_env):
    """C-07: Exporting logs while active logging is streaming is thread-safe."""
    require_features("F-10", "F-13")
    from src.utils.log_handler import GuiLogHandler

    handler = GuiLogHandler(max_entries=2000)
    logger = logging.getLogger("test_concurrent_logger")
    logger.addHandler(handler)

    stop_logging = threading.Event()

    def log_producer():
        counter = 0
        while not stop_logging.is_set() and counter < 500:
            logger.info(f"Background log message {counter}")
            counter += 1
            time.sleep(0.001)

    t = threading.Thread(target=log_producer)
    t.start()

    # Wait for logs to start flowing
    time.sleep(0.05)

    export_path = isolated_env / "concurrent_export.log"
    # Export log file concurrently with writer thread
    handler.export_to_file(str(export_path))

    stop_logging.set()
    t.join(timeout=2.0)

    assert export_path.exists()
    content = export_path.read_text(encoding="utf-8")
    assert "Background log message" in content
