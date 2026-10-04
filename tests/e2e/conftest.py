"""
Pytest configuration and fixtures for E2E opaque-box testing.
Supports isolated sandboxing, mock rclone streaming, headless GUI execution,
and progressive milestone feature probing.
"""

import os
import sys
import json
import time
import shutil
import logging
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

# Feature metadata mapping for progressive verification
FEATURE_SPEC = {
    "F-01": {"name": "Tabbed Navigation", "milestone": "M3", "module": "src.gui.app_window", "attr": "MainWindow"},
    "F-02": {"name": "Sync Progress Bar", "milestone": "M3", "module": "src.gui.app_window", "attr": "MainWindow"},
    "F-03": {"name": "Active File Indicator", "milestone": "M3", "module": "src.gui.app_window", "attr": "MainWindow"},
    "F-04": {"name": "Animated/Colored Status", "milestone": "M3", "module": "src.gui.app_window", "attr": "MainWindow"},
    "F-05": {"name": "Responsive Layout & Theme", "milestone": "M3", "module": "src.gui.app_window", "attr": "MainWindow"},
    "F-06": {"name": "Responsive UI Threading", "milestone": "M1", "module": "src.core.sync_worker", "attr": "SyncWorker"},
    "F-07": {"name": "Sync History Persistence", "milestone": "M2", "module": "src.core.history_manager", "attr": "SyncHistoryManager"},
    "F-08": {"name": "Activity History Panel", "milestone": "M3", "module": "src.gui.app_window", "attr": "MainWindow"},
    "F-09": {"name": "File Transfer Detail Inspection", "milestone": "M3", "module": "src.gui.app_window", "attr": "MainWindow"},
    "F-10": {"name": "Real-Time Log Viewer", "milestone": "M2", "module": "src.utils.log_handler", "attr": "GuiLogHandler"},
    "F-11": {"name": "Log Level Filtering", "milestone": "M2", "module": "src.utils.log_handler", "attr": "GuiLogHandler"},
    "F-12": {"name": "Log Text Search", "milestone": "M2", "module": "src.utils.log_handler", "attr": "GuiLogHandler"},
    "F-13": {"name": "Log Export Functionality", "milestone": "M2", "module": "src.utils.log_handler", "attr": "GuiLogHandler"},
    "F-14": {"name": "Tray Dynamic Status Summaries", "milestone": "M4", "module": "src.tray.tray_icon", "attr": "TrayManager"},
    "F-15": {"name": "Tray Sync Now Shortcut", "milestone": "M4", "module": "src.tray.tray_icon", "attr": "TrayManager"},
    "F-16": {"name": "Tray Pause/Resume Shortcut", "milestone": "M4", "module": "src.tray.tray_icon", "attr": "TrayManager"},
    "F-17": {"name": "Tray Open Local Vault Shortcut", "milestone": "M4", "module": "src.tray.tray_icon", "attr": "TrayManager"},
    "F-18": {"name": "Tray Open Google Drive Shortcut", "milestone": "M4", "module": "src.tray.tray_icon", "attr": "TrayManager"},
    "F-19": {"name": "Tray Open Activity Logs Shortcut", "milestone": "M4", "module": "src.tray.tray_icon", "attr": "TrayManager"},
    "F-20": {"name": "Tray Conflict Notification", "milestone": "M4", "module": "src.tray.tray_icon", "attr": "TrayManager"},
    "F-21": {"name": "Tray Fatal Error Notification", "milestone": "M4", "module": "src.tray.tray_icon", "attr": "TrayManager"},
    "F-22": {"name": "Tray Batch Complete Notification", "milestone": "M4", "module": "src.tray.tray_icon", "attr": "TrayManager"},
    "F-23": {"name": "Notification Deduplication", "milestone": "M4", "module": "src.tray.tray_icon", "attr": "TrayManager"},
    "F-24": {"name": "Streaming Subprocess Output", "milestone": "M1", "module": "src.core.sync_worker", "attr": "SyncWorker"},
    "F-25": {"name": "Decoupled Thread-Safe Events", "milestone": "M1", "module": "src.core.events", "attr": "EventDispatcher"},
    "F-26": {"name": "Graceful Error Boundaries", "milestone": "M1", "module": "src.core.sync_worker", "attr": "SyncWorker"},
    "F-27": {"name": "Minimized Startup Mode", "milestone": "M1", "module": "src.main", "attr": "main"},
    "F-28": {"name": "Comprehensive Modern Test Suite", "milestone": "M5", "module": "src.main", "attr": "main"},
}


def probe_feature(feature_id: str) -> tuple[bool, str]:
    """
    Probe if a specific feature is currently implemented and ready for execution.
    In strict mode (E2E_STRICT=1), missing features raise an AssertionError.
    In progressive mode, missing features return (False, reason).
    """
    strict = os.environ.get("E2E_STRICT") == "1"
    spec = FEATURE_SPEC.get(feature_id)
    if not spec:
        return False, f"Unknown feature ID: {feature_id}"

    # F-28: test suite integrity is meta-operational
    if feature_id == "F-28":
        return True, ""

    # Feature-specific probe heuristics
    try:
        mod_name = spec["module"]
        __import__(mod_name)
        mod = sys.modules[mod_name]
    except ImportError:
        reason = f"{feature_id} ({spec['name']}) pending in Milestone {spec['milestone']}: module '{spec['module']}' not found"
        if strict:
            pytest.fail(f"STRICT E2E FAILURE: {reason}")
        return False, reason

    attr_name = spec["attr"]
    if not hasattr(mod, attr_name):
        reason = f"{feature_id} ({spec['name']}) pending in Milestone {spec['milestone']}: attribute '{attr_name}' missing from '{mod_name}'"
        if strict:
            pytest.fail(f"STRICT E2E FAILURE: {reason}")
        return False, reason

    cls = getattr(mod, attr_name)

    # Detailed feature capability checks
    if feature_id == "F-01":  # Tabbed navigation
        has_tab = hasattr(cls, "tabview") or "tabview" in cls.__init__.__code__.co_varnames or "tabview" in cls.__dict__
        # Also check instance attributes if feasible
        if not has_tab and not hasattr(cls, "_build_tabs"):
            reason = f"{feature_id} ({spec['name']}) pending in M3: CTkTabview not yet integrated in MainWindow"
            if strict:
                pytest.fail(f"STRICT E2E FAILURE: {reason}")
            return False, reason

    elif feature_id == "F-02":  # Sync progress bar
        has_bar = hasattr(cls, "sync_progress_bar") or "sync_progress_bar" in cls.__dict__
        if not has_bar:
            reason = f"{feature_id} ({spec['name']}) pending in M3: sync_progress_bar not yet in MainWindow"
            if strict:
                pytest.fail(f"STRICT E2E FAILURE: {reason}")
            return False, reason

    elif feature_id == "F-03":  # Active file indicator
        has_file_lbl = hasattr(cls, "active_file_label") or "active_file_label" in cls.__dict__
        if not has_file_lbl:
            reason = f"{feature_id} ({spec['name']}) pending in M3: active_file_label not yet in MainWindow"
            if strict:
                pytest.fail(f"STRICT E2E FAILURE: {reason}")
            return False, reason

    elif feature_id == "F-07":  # Sync History Persistence
        if not hasattr(cls, "record_run") or not hasattr(cls, "get_recent_runs"):
            reason = f"{feature_id} ({spec['name']}) pending in M2: SyncHistoryManager interface incomplete"
            if strict:
                pytest.fail(f"STRICT E2E FAILURE: {reason}")
            return False, reason

    elif feature_id == "F-08":  # History Panel UI
        has_history_ui = hasattr(cls, "history_frame") or hasattr(cls, "_build_history_panel") or "history_view" in cls.__dict__
        if not has_history_ui:
            reason = f"{feature_id} ({spec['name']}) pending in M3: History UI panel not yet in MainWindow"
            if strict:
                pytest.fail(f"STRICT E2E FAILURE: {reason}")
            return False, reason

    elif feature_id == "F-09":  # File detail inspection
        has_inspection = hasattr(cls, "show_transfer_details") or hasattr(cls, "_show_run_details") or hasattr(cls, "detail_dialog")
        if not has_inspection:
            reason = f"{feature_id} ({spec['name']}) pending in M3: File transfer detail inspection not yet in MainWindow"
            if strict:
                pytest.fail(f"STRICT E2E FAILURE: {reason}")
            return False, reason

    elif feature_id == "F-10":  # GuiLogHandler
        if not hasattr(cls, "get_entries") or not hasattr(cls, "emit"):
            reason = f"{feature_id} ({spec['name']}) pending in M2: GuiLogHandler interface incomplete"
            if strict:
                pytest.fail(f"STRICT E2E FAILURE: {reason}")
            return False, reason

    elif feature_id == "F-11":  # Log level filtering
        # Check if get_entries accepts level_filter
        import inspect
        sig = inspect.signature(cls.get_entries)
        if "level_filter" not in sig.parameters:
            reason = f"{feature_id} ({spec['name']}) pending in M2: get_entries does not support level_filter"
            if strict:
                pytest.fail(f"STRICT E2E FAILURE: {reason}")
            return False, reason

    elif feature_id == "F-12":  # Log search
        import inspect
        sig = inspect.signature(cls.get_entries)
        if "search_query" not in sig.parameters:
            reason = f"{feature_id} ({spec['name']}) pending in M2: get_entries does not support search_query"
            if strict:
                pytest.fail(f"STRICT E2E FAILURE: {reason}")
            return False, reason

    elif feature_id == "F-13":  # Log export
        if not hasattr(cls, "export_to_file"):
            reason = f"{feature_id} ({spec['name']}) pending in M2: GuiLogHandler.export_to_file missing"
            if strict:
                pytest.fail(f"STRICT E2E FAILURE: {reason}")
            return False, reason

    elif feature_id == "F-14":  # Dynamic tray summaries
        has_dynamic = hasattr(cls, "_update_menu_summaries") or hasattr(cls, "_get_status_text") or hasattr(cls, "update_menu")
        # Check if TrayManager supports dynamic menu construction
        if not has_dynamic and not hasattr(cls, "set_vault_name"):
            reason = f"{feature_id} ({spec['name']}) pending in M4: Dynamic summaries not yet in TrayManager"
            if strict:
                pytest.fail(f"STRICT E2E FAILURE: {reason}")
            return False, reason

    elif feature_id == "F-17":  # Tray open vault
        has_open_vault = hasattr(cls, "open_vault_folder") or hasattr(cls, "_on_open_vault")
        if not has_open_vault:
            reason = f"{feature_id} ({spec['name']}) pending in M4: open_vault_folder not in TrayManager"
            if strict:
                pytest.fail(f"STRICT E2E FAILURE: {reason}")
            return False, reason

    elif feature_id == "F-18":  # Tray open gdrive
        has_open_gdrive = hasattr(cls, "open_gdrive_web") or hasattr(cls, "_on_open_gdrive")
        if not has_open_gdrive:
            reason = f"{feature_id} ({spec['name']}) pending in M4: open_gdrive_web not in TrayManager"
            if strict:
                pytest.fail(f"STRICT E2E FAILURE: {reason}")
            return False, reason

    elif feature_id == "F-19":  # Tray open logs
        has_open_logs = hasattr(cls, "open_logs") or hasattr(cls, "_on_open_logs") or hasattr(cls, "on_open_logs")
        if not has_open_logs:
            reason = f"{feature_id} ({spec['name']}) pending in M4: open_logs shortcut not in TrayManager"
            if strict:
                pytest.fail(f"STRICT E2E FAILURE: {reason}")
            return False, reason

    elif feature_id == "F-20":  # Conflict notification
        has_conflict = hasattr(cls, "notify_conflict") or hasattr(cls, "_on_conflict") or hasattr(cls, "handle_conflict")
        if not has_conflict:
            reason = f"{feature_id} ({spec['name']}) pending in M4: conflict notification not in TrayManager"
            if strict:
                pytest.fail(f"STRICT E2E FAILURE: {reason}")
            return False, reason

    elif feature_id == "F-22":  # Batch complete notification
        has_batch = hasattr(cls, "notify_batch_complete") or hasattr(cls, "_on_batch_complete")
        if not has_batch:
            reason = f"{feature_id} ({spec['name']}) pending in M4: batch notification not in TrayManager"
            if strict:
                pytest.fail(f"STRICT E2E FAILURE: {reason}")
            return False, reason

    elif feature_id == "F-24":  # Streaming subprocess
        # Check if SyncWorker uses Popen or line streaming
        import inspect
        code = inspect.getsource(cls)
        if "subprocess.Popen" not in code and "Popen" not in code:
            reason = f"{feature_id} ({spec['name']}) pending in M1: SyncWorker still uses synchronous subprocess.run"
            if strict:
                pytest.fail(f"STRICT E2E FAILURE: {reason}")
            return False, reason

    elif feature_id == "F-25":  # EventDispatcher
        if not hasattr(cls, "subscribe") or not hasattr(cls, "emit"):
            reason = f"{feature_id} ({spec['name']}) pending in M1: EventDispatcher interface incomplete"
            if strict:
                pytest.fail(f"STRICT E2E FAILURE: {reason}")
            return False, reason

    return True, ""


def require_feature(feature_id: str):
    """Skip test if feature is not yet implemented (unless in strict mode)."""
    is_ready, reason = probe_feature(feature_id)
    if not is_ready:
        pytest.skip(reason)


def require_features(*feature_ids: str):
    """Skip test if any required feature is not yet implemented."""
    for fid in feature_ids:
        require_feature(fid)


@pytest.fixture
def isolated_env(tmp_path, monkeypatch):
    """
    Isolates configuration, logs, and lock files in a sandboxed temporary directory.
    Guarantees no reads or writes to the real ~/.config/obsidian-gdrive-sync.
    """
    app_dir = tmp_path / "obsidian-gdrive-sync"
    app_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    # Patch get_app_dir in all loaded locations
    import src.utils.paths
    monkeypatch.setattr(src.utils.paths, "get_app_dir", lambda: app_dir)

    # If already imported into other modules, patch them too
    for mod_name in list(sys.modules.keys()):
        if mod_name.startswith("src.") and hasattr(sys.modules[mod_name], "get_app_dir"):
            monkeypatch.setattr(sys.modules[mod_name], "get_app_dir", lambda: app_dir)

    yield app_dir

    # Cleanup any locks
    lock_file = app_dir / "app.lock"
    if lock_file.exists():
        lock_file.unlink(missing_ok=True)


@pytest.fixture
def sample_vault(tmp_path):
    """Creates a realistic sample Obsidian vault with markdown files."""
    vault = tmp_path / "TestVault"
    vault.mkdir()
    (vault / "Notes").mkdir()
    (vault / "Notes" / "Welcome.md").write_text("# Welcome to Obsidian\nSample content", encoding="utf-8")
    (vault / "Notes" / "Project.md").write_text("# Project Notes\nTasks to complete", encoding="utf-8")
    (vault / "Daily").mkdir()
    (vault / "Daily" / "2026-10-03.md").write_text("# Daily Note\nWork log for today", encoding="utf-8")
    return vault


@pytest.fixture
def headless_gui(monkeypatch):
    """
    Ensures safe GUI execution in headless environments without physical displays.
    Mocks CustomTkinter window display operations.
    """
    # Protect against missing DISPLAY variable
    if not os.environ.get("DISPLAY"):
        monkeypatch.setenv("DISPLAY", ":99")

    # Mock tkinter / CustomTkinter display calls that require an active window server
    from unittest.mock import MagicMock
    try:
        import customtkinter as ctk
        # Preserve classes but mock display-heavy interactions
        orig_mainloop = ctk.CTk.mainloop
        monkeypatch.setattr(ctk.CTk, "mainloop", lambda self: None)
        monkeypatch.setattr(ctk.CTk, "deiconify", lambda self: None)
        monkeypatch.setattr(ctk.CTk, "lift", lambda self: None)
        monkeypatch.setattr(ctk.CTk, "update", lambda self: None)
        monkeypatch.setattr(ctk.CTk, "update_idletasks", lambda self: None)
    except Exception:
        pass


class FakeRcloneProcess:
    """Simulates a streaming rclone subprocess for testing."""
    def __init__(self, stdout_lines=None, stderr_lines=None, returncode=0, delay_per_line=0.0):
        self.stdout_lines = stdout_lines or []
        self.stderr_lines = stderr_lines or []
        self.returncode = returncode
        self.delay_per_line = delay_per_line
        self._poll_called = False

    @property
    def stdout(self):
        class LineIterator:
            def __init__(self, lines, delay):
                self.lines = list(lines)
                self.delay = delay
            def __iter__(self):
                for line in self.lines:
                    if self.delay > 0:
                        time.sleep(self.delay)
                    yield line
            def readline(self):
                if self.lines:
                    if self.delay > 0:
                        time.sleep(self.delay)
                    return self.lines.pop(0)
                return ""
            def close(self):
                pass
        return LineIterator(self.stdout_lines, self.delay_per_line)

    @property
    def stderr(self):
        class StderrIterator:
            def __init__(self, lines):
                self.lines = list(lines)
            def readline(self):
                if self.lines:
                    return self.lines.pop(0)
                return ""
            def read(self):
                return "".join(self.lines)
            def close(self):
                pass
        return StderrIterator(self.stderr_lines)

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        return self.returncode

    def kill(self):
        pass

    def terminate(self):
        pass


@pytest.fixture
def fake_rclone_factory():
    """Factory fixture to generate custom FakeRcloneProcess instances."""
    def _create(stdout_lines=None, stderr_lines=None, returncode=0, delay=0.0):
        return FakeRcloneProcess(
            stdout_lines=stdout_lines,
            stderr_lines=stderr_lines,
            returncode=returncode,
            delay_per_line=delay
        )
    return _create
