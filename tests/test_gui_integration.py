"""
Comprehensive GUI Integration Tests for Milestone 3 (Modern Responsive GUI).
Tests CTkTabview 3-tab layout, dynamic sync progress bar, active file indicator,
status badge colors, activity history manager integration, and diagnostic log viewer.
Ensures 100% headless test pass rate without DISPLAY.
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
import logging

from src.core.config import ConfigManager, ConfigData, VaultProfile
from src.core.sync_worker import SyncWorker, SyncStatus, COLOR_MAP
from src.core.rclone_manager import RcloneManager
from src.core.history_manager import SyncHistoryManager, SyncRunRecord
from src.utils.log_handler import GuiLogHandler, LogEntry
from src.core.events import (
    EventDispatcher,
    EventType,
    Event,
    StatusPayload,
    ProgressPayload,
    FilePayload,
    ConflictPayload,
    BatchPayload,
)
from src.gui.app_window import MainWindow, STATUS_COLORS, HeadlessStub, HeadlessTabview, format_byte_size


@pytest.fixture
def test_env(tmp_path):
    """Setup isolated test environment with config, history, logs, and events."""
    config_file = tmp_path / "config.json"
    history_file = tmp_path / "history.json"

    v1 = VaultProfile(id="v1", name="Principal", local_path=str(tmp_path / "vault1"), remote_folder="ObsidianVault")
    cfg = ConfigData(vaults=[v1], active_vault_id="v1")
    cfg_mgr = ConfigManager(config_file=config_file)
    cfg_mgr.save(cfg)

    history_mgr = SyncHistoryManager(history_file=history_file, max_records=50)
    log_handler = GuiLogHandler(max_entries=200)
    dispatcher = EventDispatcher()

    rclone_mock = MagicMock(spec=RcloneManager)
    rclone_mock.is_remote_configured.return_value = True

    worker = SyncWorker(config=cfg, rclone_manager=rclone_mock, event_dispatcher=dispatcher, history_manager=history_mgr)

    return {
        "tmp_path": tmp_path,
        "cfg_mgr": cfg_mgr,
        "history_mgr": history_mgr,
        "log_handler": log_handler,
        "dispatcher": dispatcher,
        "rclone_mock": rclone_mock,
        "worker": worker,
    }


# ============================================================================
# Suite 1: Tabbed Navigation & CTkTabview (F-01)
# ============================================================================
class TestTabbedNavigation:
    def test_tabview_initialization_and_three_tabs(self, test_env):
        with patch("customtkinter.CTk.__init__", return_value=None):
            win = MainWindow(
                config_manager=test_env["cfg_mgr"],
                worker=test_env["worker"],
                rclone_mgr=test_env["rclone_mock"],
                history_manager=test_env["history_mgr"],
                log_handler=test_env["log_handler"],
                event_dispatcher=test_env["dispatcher"],
            )
            assert hasattr(win, "tabview"), "MainWindow must have a tabview component"
            tabs = [win.tabview.tab("Configuración"), win.tabview.tab("Historial"), win.tabview.tab("Diagnósticos")]
            assert len(tabs) == 3
            assert tabs[0] is not None
            assert tabs[1] is not None
            assert tabs[2] is not None

    def test_tab_alias_routing(self, test_env):
        with patch("customtkinter.CTk.__init__", return_value=None):
            win = MainWindow(
                config_manager=test_env["cfg_mgr"],
                worker=test_env["worker"],
                rclone_mgr=test_env["rclone_mock"],
            )
            assert win.tabview.tab("Configuración & Sincronización") is win.tabview.tab("Configuración")
            assert win.tabview.tab("Historial de Actividad") is win.tabview.tab("Historial")
            assert win.tabview.tab("Diagnóstico & Logs") is win.tabview.tab("Diagnósticos")

    def test_build_tabs_method_exists(self):
        assert hasattr(MainWindow, "_build_tabs")
        assert callable(getattr(MainWindow, "_build_tabs"))


# ============================================================================
# Suite 2: Sync Progress Bar, Active File & Metrics (F-02, F-03)
# ============================================================================
class TestSyncProgressAndActiveFile:
    def test_set_sync_progress_bounds_and_clamping(self, test_env):
        with patch("customtkinter.CTk.__init__", return_value=None):
            win = MainWindow(
                config_manager=test_env["cfg_mgr"],
                worker=test_env["worker"],
                rclone_mgr=test_env["rclone_mock"],
            )
            assert hasattr(win, "sync_progress_bar")

            # Normal progress
            win.set_sync_progress(0.45, "45%")
            assert win.sync_progress_bar.get() == pytest.approx(0.45, rel=1e-2)
            assert win.sync_percent_label.cget("text") == "45%"

            # Upper boundary clamping
            win.set_sync_progress(1.8)
            assert win.sync_progress_bar.get() == pytest.approx(1.0, rel=1e-2)
            assert win.sync_percent_label.cget("text") == "100%"

            # Lower boundary clamping
            win.set_sync_progress(-0.5)
            assert win.sync_progress_bar.get() == pytest.approx(0.0, rel=1e-2)
            assert win.sync_percent_label.cget("text") == "0%"

    def test_set_active_file_label_formatting(self, test_env):
        with patch("customtkinter.CTk.__init__", return_value=None):
            win = MainWindow(
                config_manager=test_env["cfg_mgr"],
                worker=test_env["worker"],
                rclone_mgr=test_env["rclone_mock"],
            )
            assert hasattr(win, "active_file_label")

            win.set_active_file("Projects/WorkPlan.md")
            assert "Projects/WorkPlan.md" in win.active_file_label.cget("text")

            win.set_active_file("")
            assert "-" in win.active_file_label.cget("text")

    def test_sync_speed_and_bytes_labels(self, test_env):
        with patch("customtkinter.CTk.__init__", return_value=None):
            win = MainWindow(
                config_manager=test_env["cfg_mgr"],
                worker=test_env["worker"],
                rclone_mgr=test_env["rclone_mock"],
            )
            win.set_sync_speed("3.2 MB/s")
            assert "3.2 MB/s" in win.sync_speed_label.cget("text")

            win.set_sync_bytes(2 * 1024 * 1024, 10 * 1024 * 1024)
            assert "2.0 MB" in win.sync_bytes_label.cget("text")
            assert "10.0 MB" in win.sync_bytes_label.cget("text")

    def test_progress_updated_event_integration(self, test_env):
        with patch("customtkinter.CTk.__init__", return_value=None):
            win = MainWindow(
                config_manager=test_env["cfg_mgr"],
                worker=test_env["worker"],
                rclone_mgr=test_env["rclone_mock"],
                event_dispatcher=test_env["dispatcher"],
            )
            win._subscribe_events()

            payload = ProgressPayload(
                transferred_bytes=4 * 1024 * 1024,
                total_bytes=8 * 1024 * 1024,
                percentage=50.0,
                speed_str="1.5 MB/s",
                current_file="Notes/Research.md",
            )
            test_env["dispatcher"].emit(EventType.PROGRESS_UPDATED, payload)

            assert win.sync_progress_bar.get() == pytest.approx(0.50, rel=1e-2)
            assert "Notes/Research.md" in win.active_file_label.cget("text")
            assert "1.5 MB/s" in win.sync_speed_label.cget("text")

    def test_file_transferred_event_integration(self, test_env):
        with patch("customtkinter.CTk.__init__", return_value=None):
            win = MainWindow(
                config_manager=test_env["cfg_mgr"],
                worker=test_env["worker"],
                rclone_mgr=test_env["rclone_mock"],
                event_dispatcher=test_env["dispatcher"],
            )
            win._subscribe_events()

            payload = FilePayload(
                filename="DailyLog.md",
                size=2048,
                action="Copied (new)",
                vault_name="Principal"
            )
            test_env["dispatcher"].emit(EventType.FILE_TRANSFERRED, payload)

            assert "DailyLog.md" in win.active_file_label.cget("text")
            assert "DailyLog.md" in win.log_box.get()


# ============================================================================
# Suite 3: Status Badges & Worker Integration (F-04)
# ============================================================================
class TestStatusBadgesAndWorkerIntegration:
    def test_status_color_idle_is_green(self):
        assert STATUS_COLORS[SyncStatus.IDLE] == "#4CAF50"
        assert STATUS_COLORS[SyncStatus.SUCCESS] == "#4CAF50"
        assert STATUS_COLORS[SyncStatus.SYNCING] == "#2196F3"
        assert STATUS_COLORS[SyncStatus.PAUSED] == "#FFC107"
        assert STATUS_COLORS[SyncStatus.ERROR] == "#F44336"

    def test_status_changed_event_updates_badge(self, test_env):
        with patch("customtkinter.CTk.__init__", return_value=None):
            win = MainWindow(
                config_manager=test_env["cfg_mgr"],
                worker=test_env["worker"],
                rclone_mgr=test_env["rclone_mock"],
                event_dispatcher=test_env["dispatcher"],
            )
            win._subscribe_events()

            for status, msg in [
                (SyncStatus.SYNCING, "Sincronizando cambios..."),
                (SyncStatus.SUCCESS, "Sincronización completada"),
                (SyncStatus.PAUSED, "Sincronización pausada"),
                (SyncStatus.ERROR, "Error de red"),
                (SyncStatus.IDLE, "Inactivo"),
            ]:
                test_env["dispatcher"].emit(EventType.STATUS_CHANGED, StatusPayload(status=status, message=msg))
                assert msg in win.status_badge.cget("text")
                assert win.status_badge.cget("text_color") == STATUS_COLORS[status]

    def test_conflict_detected_event_updates_badge(self, test_env):
        with patch("customtkinter.CTk.__init__", return_value=None):
            win = MainWindow(
                config_manager=test_env["cfg_mgr"],
                worker=test_env["worker"],
                rclone_mgr=test_env["rclone_mock"],
                event_dispatcher=test_env["dispatcher"],
            )
            win._subscribe_events()

            test_env["dispatcher"].emit(EventType.CONFLICT_DETECTED, ConflictPayload(filename="Notes/Conflict.md", details="different timestamps"))
            assert "Conflicto: Notes/Conflict.md" in win.status_badge.cget("text")
            assert win.status_badge.cget("text_color") == "#FF9800"

    def test_batch_completed_resets_progress(self, test_env):
        with patch("customtkinter.CTk.__init__", return_value=None):
            win = MainWindow(
                config_manager=test_env["cfg_mgr"],
                worker=test_env["worker"],
                rclone_mgr=test_env["rclone_mock"],
                event_dispatcher=test_env["dispatcher"],
            )
            win._subscribe_events()
            win.set_sync_progress(0.8, "80%")
            win.set_active_file("Finalizing.md")

            test_env["dispatcher"].emit(EventType.BATCH_COMPLETED, BatchPayload(total_files=5, total_bytes=1000, elapsed_seconds=2.0))
            assert win.sync_progress_bar.get() == pytest.approx(1.0, rel=1e-2)
            assert win.sync_percent_label.cget("text") == "100%"
            assert "-" in win.active_file_label.cget("text")


# ============================================================================
# Suite 4: Activity History Integration (F-08, F-09)
# ============================================================================
class TestActivityHistoryIntegration:
    def test_history_view_populates_from_history_manager(self, test_env):
        # Seed 3 records into persistence
        r1 = SyncRunRecord(id="r1", timestamp="2026-10-03T10:00:00Z", vault_name="Principal", status="SUCCESS", duration_seconds=1.2, files_transferred=["a.md"])
        r2 = SyncRunRecord(id="r2", timestamp="2026-10-03T10:05:00Z", vault_name="Principal", status="ERROR", duration_seconds=0.8, files_transferred=[], error_message="Network down")
        r3 = SyncRunRecord(id="r3", timestamp="2026-10-03T10:10:00Z", vault_name="Principal", status="SUCCESS", duration_seconds=2.5, files_transferred=["b.md", "c.md"])

        test_env["history_mgr"].record_run(r1)
        test_env["history_mgr"].record_run(r2)
        test_env["history_mgr"].record_run(r3)

        with patch("customtkinter.CTk.__init__", return_value=None):
            win = MainWindow(
                config_manager=test_env["cfg_mgr"],
                worker=test_env["worker"],
                rclone_mgr=test_env["rclone_mock"],
                history_manager=test_env["history_mgr"],
            )
            records = win.get_displayed_history_records()
            assert len(records) == 3
            # Reverse chronological check
            assert records[0].id == "r3"
            assert records[1].id == "r2"
            assert records[2].id == "r1"

    def test_history_empty_state(self, test_env):
        with patch("customtkinter.CTk.__init__", return_value=None):
            win = MainWindow(
                config_manager=test_env["cfg_mgr"],
                worker=test_env["worker"],
                rclone_mgr=test_env["rclone_mock"],
                history_manager=test_env["history_mgr"],
            )
            records = win.get_displayed_history_records()
            assert records == []

    def test_history_clear_purges_persistence_and_view(self, test_env):
        r1 = SyncRunRecord(id="r1", timestamp="2026-10-03T10:00:00Z", vault_name="Principal", status="SUCCESS", duration_seconds=1.0)
        test_env["history_mgr"].record_run(r1)

        with patch("customtkinter.CTk.__init__", return_value=None):
            win = MainWindow(
                config_manager=test_env["cfg_mgr"],
                worker=test_env["worker"],
                rclone_mgr=test_env["rclone_mock"],
                history_manager=test_env["history_mgr"],
            )
            assert len(win.get_displayed_history_records()) == 1

            win.clear_history()
            assert len(win.get_displayed_history_records()) == 0
            assert test_env["history_mgr"].get_recent_runs() == []

    def test_show_transfer_details_record_inspection(self, test_env):
        r1 = SyncRunRecord(
            id="sync_inspect_99",
            timestamp="2026-10-03T11:00:00Z",
            vault_name="Principal",
            status="SUCCESS",
            duration_seconds=3.4,
            files_transferred=["Chapter1.md", "Chapter2.md"],
            bytes_transferred=4096
        )
        test_env["history_mgr"].record_run(r1)

        with patch("customtkinter.CTk.__init__", return_value=None):
            win = MainWindow(
                config_manager=test_env["cfg_mgr"],
                worker=test_env["worker"],
                rclone_mgr=test_env["rclone_mock"],
                history_manager=test_env["history_mgr"],
            )
            details = win.show_transfer_details("sync_inspect_99")
            assert details is not None
            assert details["id"] == "sync_inspect_99"
            assert details["status"] == "SUCCESS"
            assert details["files_transferred"] == ["Chapter1.md", "Chapter2.md"]
            assert details["duration_seconds"] == 3.4
            assert details["bytes_transferred"] == 4096

    def test_history_auto_refresh_on_batch_complete_event(self, test_env):
        with patch("customtkinter.CTk.__init__", return_value=None):
            win = MainWindow(
                config_manager=test_env["cfg_mgr"],
                worker=test_env["worker"],
                rclone_mgr=test_env["rclone_mock"],
                history_manager=test_env["history_mgr"],
                event_dispatcher=test_env["dispatcher"],
            )
            win._subscribe_events()
            assert len(win.get_displayed_history_records()) == 0

            # Record a run in history_mgr and trigger batch completed
            r_new = SyncRunRecord(id="r_auto", timestamp="2026-10-03T12:00:00Z", vault_name="Principal", status="SUCCESS", duration_seconds=1.1)
            test_env["history_mgr"].record_run(r_new)

            test_env["dispatcher"].emit(EventType.BATCH_COMPLETED, BatchPayload(total_files=1, total_bytes=100, elapsed_seconds=1.1))
            assert len(win.get_displayed_history_records()) == 1
            assert win.get_displayed_history_records()[0].id == "r_auto"


# ============================================================================
# Suite 5: Diagnostic Log Viewer Integration (F-10, F-11, F-12, F-13)
# ============================================================================
class TestDiagnosticLogViewerIntegration:
    def test_log_viewer_displays_buffered_records(self, test_env):
        logger = logging.getLogger("test_gui_logger_buffered")
        logger.setLevel(logging.DEBUG)
        logger.addHandler(test_env["log_handler"])
        logger.info("Buffer record Alpha")
        logger.warning("Buffer record Beta")

        with patch("customtkinter.CTk.__init__", return_value=None):
            win = MainWindow(
                config_manager=test_env["cfg_mgr"],
                worker=test_env["worker"],
                rclone_mgr=test_env["rclone_mock"],
                log_handler=test_env["log_handler"],
            )
            entries = win.apply_log_filters()
            assert len(entries) == 2
            log_content = win.log_box.get()
            assert "Buffer record Alpha" in log_content
            assert "Buffer record Beta" in log_content

    def test_log_viewer_level_filter(self, test_env):
        logger = logging.getLogger("test_gui_logger_filter")
        logger.setLevel(logging.DEBUG)
        logger.addHandler(test_env["log_handler"])
        logger.info("Info log")
        logger.warning("Warning log")
        logger.error("Error log")

        with patch("customtkinter.CTk.__init__", return_value=None):
            win = MainWindow(
                config_manager=test_env["cfg_mgr"],
                worker=test_env["worker"],
                rclone_mgr=test_env["rclone_mock"],
                log_handler=test_env["log_handler"],
            )
            win.log_filter_menu.set("ERROR")
            entries = win.apply_log_filters()
            assert len(entries) == 1
            assert entries[0].level == "ERROR"
            assert "Error log" in win.log_box.get()
            assert "Info log" not in win.log_box.get()

    def test_log_viewer_search_filter(self, test_env):
        logger = logging.getLogger("test_gui_logger_search")
        logger.setLevel(logging.DEBUG)
        logger.addHandler(test_env["log_handler"])
        logger.info("Regular message")
        logger.info("SecretToken_12345 occurred")

        with patch("customtkinter.CTk.__init__", return_value=None):
            win = MainWindow(
                config_manager=test_env["cfg_mgr"],
                worker=test_env["worker"],
                rclone_mgr=test_env["rclone_mock"],
                log_handler=test_env["log_handler"],
            )
            win.log_search_entry.delete(0, "end")
            win.log_search_entry.insert(0, "SecretToken_12345")
            entries = win.apply_log_filters()
            assert len(entries) == 1
            assert "SecretToken_12345" in entries[0].message

    def test_log_viewer_realtime_stream_listener(self, test_env):
        logger = logging.getLogger("test_gui_logger_live")
        logger.setLevel(logging.DEBUG)
        logger.addHandler(test_env["log_handler"])

        with patch("customtkinter.CTk.__init__", return_value=None):
            win = MainWindow(
                config_manager=test_env["cfg_mgr"],
                worker=test_env["worker"],
                rclone_mgr=test_env["rclone_mock"],
                log_handler=test_env["log_handler"],
            )
            win._subscribe_events()

            logger.info("Live real-time streamed line")
            assert "Live real-time streamed line" in win.log_box.get()

    def test_log_viewer_export_action(self, test_env, tmp_path):
        logger = logging.getLogger("test_gui_logger_export")
        logger.setLevel(logging.DEBUG)
        logger.addHandler(test_env["log_handler"])
        logger.info("Line to be exported to disk")

        with patch("customtkinter.CTk.__init__", return_value=None):
            win = MainWindow(
                config_manager=test_env["cfg_mgr"],
                worker=test_env["worker"],
                rclone_mgr=test_env["rclone_mock"],
                log_handler=test_env["log_handler"],
            )
            export_dest = tmp_path / "exported_test.log"
            win.export_logs(str(export_dest))

            assert export_dest.exists()
            content = export_dest.read_text(encoding="utf-8")
            assert "Line to be exported to disk" in content

    def test_log_viewer_listener_cleanup_on_destroy(self, test_env):
        with patch("customtkinter.CTk.__init__", return_value=None):
            win = MainWindow(
                config_manager=test_env["cfg_mgr"],
                worker=test_env["worker"],
                rclone_mgr=test_env["rclone_mock"],
                log_handler=test_env["log_handler"],
            )
            win._subscribe_events()
            assert len(test_env["log_handler"]._listeners) >= 1

            win.destroy()
            assert len(test_env["log_handler"]._listeners) == 0


# ============================================================================
# Suite 6: Headless Compatibility & Thread Marshaling
# ============================================================================
class TestHeadlessCompatibility:
    def test_headless_stub_mechanics(self):
        stub = HeadlessStub(text="Hello", value=42.0)
        assert stub.cget("text") == "Hello"
        assert stub.get() == 42.0

        stub.configure(text="World")
        assert stub.cget("text") == "World"

        stub.set(99.5)
        assert stub.get() == 99.5

        stub.insert(0, "prefix_")
        assert stub.get() == "prefix_"
        stub.delete(0, "end")
        assert stub.get() == ""

    def test_headless_tabview_mechanics(self):
        tabview = HeadlessTabview()
        assert tabview.tab("Configuración") is not None
        assert tabview.tab("Historial") is not None
        assert tabview.tab("Diagnósticos") is not None
        assert tabview.tab("Configuración & Sincronización") is tabview.tab("Configuración")

    def test_run_on_ui_thread_safe_execution(self, test_env):
        with patch("customtkinter.CTk.__init__", return_value=None):
            win = MainWindow(
                config_manager=test_env["cfg_mgr"],
                worker=test_env["worker"],
                rclone_mgr=test_env["rclone_mock"],
            )
            called = []

            def callback(x, y):
                called.append(x + y)

            win._run_on_ui_thread(callback, 10, 20)
            assert called == [30]

    def test_format_byte_size_helper(self):
        assert format_byte_size(500) == "500 B"
        assert format_byte_size(1024) == "1.0 KB"
        assert format_byte_size(1024 * 1024 * 5) == "5.0 MB"
        assert format_byte_size(1024 * 1024 * 1024 * 2) == "2.00 GB"
        assert format_byte_size("invalid") == "0 B"

    def test_execute_auth_process_success(self, test_env):
        with patch("customtkinter.CTk.__init__", return_value=None):
            win = MainWindow(
                config_manager=test_env["cfg_mgr"],
                worker=test_env["worker"],
                rclone_mgr=test_env["rclone_mock"],
            )
            fake_stdout = [
                "NOTICE: If your browser doesn't open automatically go to the following link: http://127.0.0.1:53682/auth?state=xyz123\n",
                "NOTICE: Waiting for code...\n",
                "NOTICE: Got code\n",
            ]
            mock_proc = MagicMock()
            mock_proc.stdout.readline.side_effect = fake_stdout + [""]
            mock_proc.wait.return_value = 0

            with patch("subprocess.Popen", return_value=mock_proc), patch("webbrowser.open") as mock_browser:
                result = win._execute_auth_process(["rclone", "config", "reconnect", "gdrive:", "--auto-confirm"])
                assert result is True
                mock_browser.assert_called_once_with("http://127.0.0.1:53682/auth?state=xyz123")

    def test_execute_auth_process_handles_failure(self, test_env):
        with patch("customtkinter.CTk.__init__", return_value=None):
            win = MainWindow(
                config_manager=test_env["cfg_mgr"],
                worker=test_env["worker"],
                rclone_mgr=test_env["rclone_mock"],
            )
            mock_proc = MagicMock()
            mock_proc.stdout.readline.side_effect = ["Error: token expired\n", ""]
            mock_proc.wait.return_value = 1

            with patch("subprocess.Popen", return_value=mock_proc):
                result = win._execute_auth_process(["rclone", "config", "reconnect", "gdrive:", "--auto-confirm"])
                assert result is False
