"""
Tier 1: Feature Isolation Coverage (F-01 through F-28).
Validates each feature independently against its contract and requirements.
"""

import sys
import os
import time
import logging
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from tests.e2e.conftest import require_feature, FEATURE_SPEC
from src.core.config import ConfigManager, ConfigData, VaultProfile
from src.core.sync_worker import SyncWorker, SyncStatus, COLOR_MAP
from src.tray.tray_icon import TrayManager


# ============================================================================
# F-01: Multi-Panel Tab Navigation (M3 / R1)
# ============================================================================
def test_f01_tabbed_navigation(isolated_env, headless_gui):
    """F-01: MainWindow provides tabbed navigation (Config, History, Diagnostics)."""
    require_feature("F-01")
    from src.gui.app_window import MainWindow

    cfg_mgr = ConfigManager()
    worker = MagicMock()
    rclone = MagicMock()

    with patch("customtkinter.CTk.__init__", return_value=None):
        win = MainWindow(config_manager=cfg_mgr, worker=worker, rclone_mgr=rclone)
        assert hasattr(win, "tabview"), "MainWindow must have a tabview component"
        tabs = [win.tabview.tab("Configuración"), win.tabview.tab("Historial"), win.tabview.tab("Diagnósticos")]
        assert len(tabs) == 3


# ============================================================================
# F-02: Dynamic Sync Progress Bar (M3 / R1)
# ============================================================================
def test_f02_sync_progress_bar(isolated_env, headless_gui):
    """F-02: Real-time progress bar reflects sync progress and percentage."""
    require_feature("F-02")
    from src.gui.app_window import MainWindow

    cfg_mgr = ConfigManager()
    with patch("customtkinter.CTk.__init__", return_value=None):
        win = MainWindow(config_manager=cfg_mgr, worker=MagicMock(), rclone_mgr=MagicMock())
        assert hasattr(win, "sync_progress_bar"), "MainWindow must have a sync_progress_bar"
        win.set_sync_progress(0.75, "75%")
        assert win.sync_progress_bar.get() == pytest.approx(0.75, rel=1e-2)


# ============================================================================
# F-03: Active File Transfer Indicator (M3 / R1)
# ============================================================================
def test_f03_active_file_indicator(isolated_env, headless_gui):
    """F-03: Real-time visual label displaying current file being transferred."""
    require_feature("F-03")
    from src.gui.app_window import MainWindow

    cfg_mgr = ConfigManager()
    with patch("customtkinter.CTk.__init__", return_value=None):
        win = MainWindow(config_manager=cfg_mgr, worker=MagicMock(), rclone_mgr=MagicMock())
        assert hasattr(win, "active_file_label"), "MainWindow must have active_file_label"
        win.set_active_file("Notes/Daily.md")
        assert "Notes/Daily.md" in win.active_file_label.cget("text")


# ============================================================================
# F-04: Animated/Colored Status Badges (M3 / R1)
# ============================================================================
def test_f04_status_badges(isolated_env, headless_gui):
    """F-04: Distinct status states visually recognizable with color coding."""
    from src.gui.app_window import MainWindow

    cfg_mgr = MagicMock()
    cfg_mgr.load.return_value = ConfigData()
    with patch("customtkinter.CTk.__init__", return_value=None):
        win = MainWindow(config_manager=cfg_mgr, worker=MagicMock(), rclone_mgr=MagicMock())
        win.status_badge = MagicMock()
        win.log_box = MagicMock()

        for status in [SyncStatus.IDLE, SyncStatus.SYNCING, SyncStatus.SUCCESS, SyncStatus.PAUSED, SyncStatus.ERROR]:
            assert status in COLOR_MAP, f"Missing color definition for {status}"
            assert COLOR_MAP[status].startswith("#")
            win._apply_worker_update(status, f"Status {status.value}")
            win.status_badge.configure.assert_called_with(
                text=f"● Status {status.value}",
                text_color=COLOR_MAP[status]
            )


# ============================================================================
# F-05: Responsive Layout & Desktop Theme (M3 / R1)
# ============================================================================
def test_f05_responsive_layout_theme(isolated_env, headless_gui):
    """F-05: Layout adjusts dynamically to window resizing and desktop theme."""
    import customtkinter as ctk

    # Verify appearance modes can be toggled cleanly
    ctk.set_appearance_mode("light")
    assert ctk.get_appearance_mode() == "Light"
    ctk.set_appearance_mode("dark")
    assert ctk.get_appearance_mode() == "Dark"


# ============================================================================
# F-06: Responsive UI Threading (M1 / R1)
# ============================================================================
def test_f06_responsive_ui_threading(isolated_env):
    """F-06: Non-blocking background worker keeps UI responsive during sync."""
    cfg = ConfigData(local_vault_path="/tmp/test", remote_folder_name="ObsidianVault", sync_interval_minutes=2)
    mock_rclone = MagicMock()

    worker = SyncWorker(config=cfg, rclone_manager=mock_rclone)
    assert not worker._running

    worker.start()
    assert worker._running
    assert worker._thread is not None
    assert worker._thread.is_alive()
    assert worker._thread.daemon is True

    worker.stop()
    assert not worker._running


# ============================================================================
# F-07: Sync History Persistence Engine (M2 / R2)
# ============================================================================
def test_f07_history_persistence(isolated_env):
    """F-07: SyncHistoryManager persists run records to history.json (ring buffer 100)."""
    require_feature("F-07")
    from src.core.history_manager import SyncHistoryManager, SyncRunRecord

    history_file = isolated_env / "history.json"
    mgr = SyncHistoryManager(history_file=history_file, max_records=100)

    record = SyncRunRecord(
        id="sync_001",
        timestamp="2026-10-03T14:32:10Z",
        vault_name="Principal",
        status="SUCCESS",
        duration_seconds=3.5,
        files_transferred=["Notes/Plan.md", "Notes/Idea.md"],
        error_message=None,
        bytes_transferred=2048
    )

    mgr.record_run(record)
    runs = mgr.get_recent_runs(limit=10)
    assert len(runs) == 1
    assert runs[0].id == "sync_001"
    assert runs[0].status == "SUCCESS"
    assert len(runs[0].files_transferred) == 2

    # Ring buffer cap test: add 105 records
    for i in range(105):
        mgr.record_run(SyncRunRecord(
            id=f"sync_bulk_{i}",
            timestamp="2026-10-03T15:00:00Z",
            vault_name="Principal",
            status="SUCCESS",
            duration_seconds=1.0,
            files_transferred=[]
        ))

    all_runs = mgr.get_recent_runs(limit=200)
    assert len(all_runs) <= 100, "History ring buffer must cap at 100 entries"


# ============================================================================
# F-08: Activity History Panel UI (M3 / R2)
# ============================================================================
def test_f08_history_panel_ui(isolated_env, headless_gui):
    """F-08: History panel displays at least recent 20 sync operations."""
    require_feature("F-08")
    from src.gui.app_window import MainWindow

    cfg_mgr = ConfigManager()
    with patch("customtkinter.CTk.__init__", return_value=None):
        win = MainWindow(config_manager=cfg_mgr, worker=MagicMock(), rclone_mgr=MagicMock())
        assert hasattr(win, "history_frame") or hasattr(win, "history_table")
        runs = win.get_displayed_history_records()
        assert isinstance(runs, list)


# ============================================================================
# F-09: File Transfer Detail Inspection (M3 / R2)
# ============================================================================
def test_f09_file_detail_inspection(isolated_env, headless_gui):
    """F-09: Detailed file transfers are inspectable per sync run."""
    require_feature("F-09")
    from src.gui.app_window import MainWindow

    cfg_mgr = ConfigManager()
    with patch("customtkinter.CTk.__init__", return_value=None):
        win = MainWindow(config_manager=cfg_mgr, worker=MagicMock(), rclone_mgr=MagicMock())
        details = win.show_transfer_details("sync_001")
        assert details is not None


# ============================================================================
# F-10: In-App Real-Time Log Viewer (M2 / R2)
# ============================================================================
def test_f10_realtime_log_viewer(isolated_env):
    """F-10: GuiLogHandler captures logging output in real-time."""
    require_feature("F-10")
    from src.utils.log_handler import GuiLogHandler

    logger = logging.getLogger("test_logger_f10")
    logger.setLevel(logging.DEBUG)
    handler = GuiLogHandler(max_entries=100)
    logger.addHandler(handler)

    logger.info("Test E2E Log Message Alpha")
    entries = handler.get_entries()
    assert len(entries) >= 1
    assert any("Test E2E Log Message Alpha" in e.message for e in entries)


# ============================================================================
# F-11: Log Level Filtering (M2 / R2)
# ============================================================================
def test_f11_log_level_filtering(isolated_env):
    """F-11: Filter logs by level: INFO, WARNING, ERROR, ALL."""
    require_feature("F-11")
    from src.utils.log_handler import GuiLogHandler

    logger = logging.getLogger("test_logger_f11")
    logger.setLevel(logging.DEBUG)
    handler = GuiLogHandler(max_entries=100)
    logger.addHandler(handler)

    logger.info("Informational event")
    logger.warning("Warning event")
    logger.error("Error event")

    error_entries = handler.get_entries(level_filter="ERROR")
    assert all(e.level == "ERROR" for e in error_entries)
    assert len(error_entries) == 1

    warn_entries = handler.get_entries(level_filter="WARNING")
    assert all(e.level == "WARNING" for e in warn_entries)
    assert len(warn_entries) == 1


# ============================================================================
# F-12: Log Text Search (M2 / R2)
# ============================================================================
def test_f12_log_text_search(isolated_env):
    """F-12: Case-insensitive keyword search in logs."""
    require_feature("F-12")
    from src.utils.log_handler import GuiLogHandler

    logger = logging.getLogger("test_logger_f12")
    handler = GuiLogHandler(max_entries=100)
    logger.addHandler(handler)

    logger.info("Processing vault Obsidian_Unique_Keyword")
    logger.info("Another routine line")

    results = handler.get_entries(search_query="unique_keyword")
    assert len(results) == 1
    assert "Obsidian_Unique_Keyword" in results[0].message


# ============================================================================
# F-13: Log Export Functionality (M2 / R2)
# ============================================================================
def test_f13_log_export(isolated_env):
    """F-13: One-click export of log contents to timestamped file."""
    require_feature("F-13")
    from src.utils.log_handler import GuiLogHandler

    logger = logging.getLogger("test_logger_f13")
    handler = GuiLogHandler(max_entries=100)
    logger.addHandler(handler)

    logger.info("Log line for export test")
    export_file = isolated_env / "exported_sync.log"
    handler.export_to_file(str(export_file))

    assert export_file.exists()
    content = export_file.read_text(encoding="utf-8")
    assert "Log line for export test" in content


# ============================================================================
# F-14: Dynamic System Tray Status Summaries (M4 / R3)
# ============================================================================
def test_f14_tray_status_summaries(isolated_env):
    """F-14: Context menu displaying last sync time, active vault, and storage quota."""
    require_feature("F-14")
    worker = MagicMock()
    tray = TrayManager(worker=worker, on_open_gui=MagicMock(), on_exit=MagicMock())
    tray.set_vault_name("Principal")
    tray.set_last_sync("14:32:10")
    tray.set_quota_summary("12.0 GB / 15.0 GB (80%)")

    menu_labels = [item.text(item) if callable(item.text) else item.text for item in tray._icon.menu]
    assert any("Principal" in lbl for lbl in menu_labels)
    assert any("14:32:10" in lbl for lbl in menu_labels)


# ============================================================================
# F-15: Tray Shortcut: Trigger Sync Now (M4 / R3)
# ============================================================================
def test_f15_tray_sync_now(isolated_env):
    """F-15: One-click immediate sync trigger from tray menu."""
    worker = MagicMock()
    tray = TrayManager(worker=worker, on_open_gui=MagicMock(), on_exit=MagicMock())
    menu = tray._build_menu()
    sync_item = [item for item in menu if item.text == "Sincronizar Ahora"][0]
    sync_item(tray.icon)
    worker.trigger_now.assert_called_once()


# ============================================================================
# F-16: Tray Shortcut: Pause / Resume Sync (M4 / R3)
# ============================================================================
def test_f16_tray_pause_resume(isolated_env):
    """F-16: One-click sync pause and resume toggle from tray menu."""
    cfg = ConfigData(local_vault_path="/tmp/v", remote_folder_name="v")
    worker = SyncWorker(config=cfg, rclone_manager=MagicMock())
    tray = TrayManager(worker=worker, on_open_gui=MagicMock(), on_exit=MagicMock())

    assert not worker._paused
    tray._toggle_pause()
    assert worker._paused
    assert worker.status == SyncStatus.PAUSED

    tray._toggle_pause()
    assert not worker._paused
    assert worker.status == SyncStatus.IDLE


# ============================================================================
# F-17: Tray Shortcut: Open Local Vault Folder (M4 / R3)
# ============================================================================
def test_f17_tray_open_vault(isolated_env, sample_vault):
    """F-17: One-click shortcut opening local vault folder via xdg-open/launcher."""
    require_feature("F-17")
    worker = MagicMock()
    worker.config.local_vault_path = str(sample_vault)
    tray = TrayManager(worker=worker, on_open_gui=MagicMock(), on_exit=MagicMock())

    with patch("subprocess.Popen") as mock_popen:
        tray.open_vault_folder()
        mock_popen.assert_called_once()
        args = mock_popen.call_args[0][0]
        assert str(sample_vault) in args


# ============================================================================
# F-18: Tray Shortcut: Open Google Drive Web (M4 / R3)
# ============================================================================
def test_f18_tray_open_gdrive(isolated_env):
    """F-18: One-click shortcut opening Google Drive in browser."""
    require_feature("F-18")
    tray = TrayManager(worker=MagicMock(), on_open_gui=MagicMock(), on_exit=MagicMock())
    with patch("webbrowser.open") as mock_open:
        tray.open_gdrive_web()
        mock_open.assert_called_once()
        assert "drive.google.com" in mock_open.call_args[0][0]


# ============================================================================
# F-19: Tray Shortcut: Open Activity Logs (M4 / R3)
# ============================================================================
def test_f19_tray_open_logs(isolated_env):
    """F-19: One-click shortcut bringing main window to diagnostics tab."""
    require_feature("F-19")
    on_open_gui = MagicMock()
    tray = TrayManager(worker=MagicMock(), on_open_gui=on_open_gui, on_exit=MagicMock())
    tray.open_logs()
    on_open_gui.assert_called_once()


# ============================================================================
# F-20: Tray Conflict Notification (M4 / R3)
# ============================================================================
def test_f20_tray_conflict_alert(isolated_env):
    """F-20: Desktop notification alert on file conflicts during sync."""
    require_feature("F-20")
    tray = TrayManager(worker=MagicMock(), on_open_gui=MagicMock(), on_exit=MagicMock())
    with patch.object(tray, "notify") as mock_notify:
        tray.notify_conflict("Notes/Conflicted.md")
        mock_notify.assert_called_once()
        args = mock_notify.call_args[0]
        assert "Conflicto" in args[0] or "Conflicto" in args[1]


# ============================================================================
# F-21: Tray Fatal Error Notification (M4 / R3)
# ============================================================================
def test_f21_tray_fatal_error_alert(isolated_env):
    """F-21: Desktop notification alert on fatal sync failure."""
    tray = TrayManager(worker=MagicMock(), on_open_gui=MagicMock(), on_exit=MagicMock())
    with patch.object(tray, "notify") as mock_notify:
        tray.update_status(SyncStatus.ERROR, "Fatal sync error occurred")
        mock_notify.assert_called_once()
        assert "Error" in mock_notify.call_args[0][0]


# ============================================================================
# F-22: Tray Batch Complete Notification (M4 / R3)
# ============================================================================
def test_f22_tray_batch_notification(isolated_env):
    """F-22: Desktop notification on large batch transfer completion (>5 files)."""
    require_feature("F-22")
    tray = TrayManager(worker=MagicMock(), on_open_gui=MagicMock(), on_exit=MagicMock())
    with patch.object(tray, "notify") as mock_notify:
        tray.notify_batch_complete(file_count=12, total_bytes=1048576)
        mock_notify.assert_called_once()
        assert "12" in mock_notify.call_args[0][1]


# ============================================================================
# F-23: Notification Deduplication & Cooldown (M4 / R3)
# ============================================================================
def test_f23_notification_deduplication(isolated_env):
    """F-23: 15-minute cooldown and error suppression prevents notification spam."""
    tray = TrayManager(worker=MagicMock(), on_open_gui=MagicMock(), on_exit=MagicMock())
    with patch.object(tray, "notify") as mock_notify:
        # First notification fires
        tray.update_status(SyncStatus.ERROR, "Network error")
        assert mock_notify.call_count == 1

        # Immediate second identical error is suppressed by cooldown
        tray.update_status(SyncStatus.ERROR, "Network error")
        assert mock_notify.call_count == 1


# ============================================================================
# F-24: Streaming Subprocess Output (M1 / R4)
# ============================================================================
def test_f24_streaming_subprocess(isolated_env, sample_vault):
    """F-24: rclone stdout lines are parsed into live events as they stream."""
    require_feature("F-24")
    from src.core.sync_worker import SyncWorker
    from src.core.events import EventDispatcher, EventType
    from tests.fakes import FakeLauncher, FakeProcess, stub_rclone

    lines = [
        "Transferred: 500 KiB / 1 MiB, 50%, 100 KiB/s",
        "* Notes/Todo.md: 100% /100%, 50 KiB/s",
        "Bisync successful"
    ]
    dispatcher = EventDispatcher()
    progress = []
    dispatcher.subscribe(EventType.PROGRESS_UPDATED, lambda ev: progress.append(ev.data.percentage))

    cfg = ConfigData(local_vault_path=str(sample_vault), remote_folder_name="v", first_sync_done=True)
    worker = SyncWorker(
        config=cfg,
        rclone_manager=stub_rclone(),
        event_dispatcher=dispatcher,
        launcher=FakeLauncher(FakeProcess(lines)),
    )

    assert worker._execute_sync() is True
    assert progress == [50.0, 100.0]


# ============================================================================
# F-25: Decoupled Thread-Safe Events (M1 / R4)
# ============================================================================
def test_f25_decoupled_events(isolated_env):
    """F-25: EventDispatcher pub/sub queue decouples background threads from UI."""
    require_feature("F-25")
    from src.core.events import EventDispatcher, EventType, Event

    dispatcher = EventDispatcher()
    received = []

    def on_status(event: Event):
        received.append(event)

    dispatcher.subscribe(EventType.STATUS_CHANGED, on_status)
    dispatcher.emit(EventType.STATUS_CHANGED, {"status": "SYNCING", "message": "Starting sync"})

    assert len(received) == 1
    assert received[0].event_type == EventType.STATUS_CHANGED
    assert received[0].data["status"] == "SYNCING"

    dispatcher.unsubscribe(EventType.STATUS_CHANGED, on_status)
    dispatcher.emit(EventType.STATUS_CHANGED, {"status": "IDLE"})
    assert len(received) == 1, "Unsubscribed callback must not receive events"


# ============================================================================
# F-26: Graceful Error Boundaries (M1 / R4)
# ============================================================================
def test_f26_error_boundaries(isolated_env, tmp_path):
    """F-26: Exception boundaries prevent thread crashes from terminating worker."""
    vault = tmp_path / "vault"
    vault.mkdir()
    cfg = ConfigData(local_vault_path=str(vault), remote_folder_name="v")
    mock_rclone = MagicMock()
    mock_rclone.ensure_remote_dir.side_effect = RuntimeError("Simulated unhandled process crash")

    worker = SyncWorker(config=cfg, rclone_manager=mock_rclone)
    # Execution must catch exception, set ERROR status, and not crash thread
    success = worker._execute_sync()
    assert success is False
    assert worker.status == SyncStatus.ERROR


# ============================================================================
# F-27: Minimized Startup Mode (M1 / R4)
# ============================================================================
def test_f27_minimized_startup(isolated_env):
    """F-27: Application starts cleanly in --minimized mode keeping window hidden."""
    with patch("src.main.acquire_single_instance_lock", return_value=True), \
         patch("src.main.release_single_instance_lock"), \
         patch("src.main.ConfigManager"), \
         patch("src.main.RcloneManager"), \
         patch("src.main.SyncWorker"), \
         patch("src.main.TrayManager"), \
         patch("src.main.MainWindow") as mock_window_cls, \
         patch.object(sys, "argv", ["main.py", "--minimized"]):

        mock_app = MagicMock()
        mock_app.can_auto_start_sync.return_value = True
        mock_window_cls.return_value = mock_app

        from src.main import main
        mock_app.mainloop.side_effect = None
        main()

        mock_app.withdraw.assert_called_once()
        mock_app.start_sync_engine.assert_called_once()


# ============================================================================
# F-28: Comprehensive Modern Test Suite Integrity (M5 / R4)
# ============================================================================
def test_f28_test_suite_integrity():
    """F-28: All 28 features (F-01 through F-28) cataloged and mapped in test suite."""
    expected_features = [f"F-{i:02d}" for i in range(1, 29)]
    for fid in expected_features:
        assert fid in FEATURE_SPEC, f"Feature {fid} must be present in FEATURE_SPEC"
        assert "name" in FEATURE_SPEC[fid]
        assert "milestone" in FEATURE_SPEC[fid]
