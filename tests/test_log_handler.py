"""
Comprehensive Unit Test Suite for GuiLogHandler and LogEntry.
Tests in-memory ring buffer, level filtering, case-insensitive search,
atomic file export, thread safety, listeners, and logger singleton integration.
"""
import logging
import os
import threading
import time
from pathlib import Path
from unittest.mock import patch
import pytest

from src.utils.log_handler import GuiLogHandler, LogEntry
from src.utils.logger import (
    get_gui_log_handler,
    reset_gui_log_handler,
    setup_logger,
)


class TestLogEntryModel:
    def test_log_entry_fields(self):
        entry = LogEntry(
            timestamp="2026-10-03 12:00:00",
            level="INFO",
            message="Test message",
            logger_name="test_logger",
        )
        assert entry.timestamp == "2026-10-03 12:00:00"
        assert entry.level == "INFO"
        assert entry.message == "Test message"
        assert entry.logger_name == "test_logger"

    def test_log_entry_format_and_str(self):
        entry = LogEntry(
            timestamp="2026-10-03 12:00:00",
            level="WARNING",
            message="Check disk space",
        )
        expected = "2026-10-03 12:00:00 [WARNING] Check disk space"
        assert entry.format() == expected
        assert str(entry) == expected

    def test_log_entry_to_dict(self):
        entry = LogEntry(
            timestamp="2026-10-03 12:00:00",
            level="ERROR",
            message="Fatal connection drop",
            logger_name="network",
        )
        d = entry.to_dict()
        assert d == {
            "timestamp": "2026-10-03 12:00:00",
            "level": "ERROR",
            "message": "Fatal connection drop",
            "logger_name": "network",
        }

    def test_log_entry_dataclass_equality(self):
        e1 = LogEntry("2026-10-03 12:00:00", "INFO", "msg")
        e2 = LogEntry("2026-10-03 12:00:00", "INFO", "msg")
        assert e1 == e2


class TestGuiLogHandlerInitialization:
    def test_init_default_max_entries_1000(self):
        handler = GuiLogHandler()
        assert handler.max_entries == 1000

    def test_init_custom_max_entries(self):
        handler = GuiLogHandler(max_entries=50)
        assert handler.max_entries == 50

    def test_is_logging_handler_subclass(self):
        handler = GuiLogHandler()
        assert isinstance(handler, logging.Handler)

    def test_init_empty_entries(self):
        handler = GuiLogHandler()
        assert handler.get_entries() == []
        assert len(handler) == 0

    def test_bool_truthiness_when_empty_and_populated(self):
        handler = GuiLogHandler()
        assert len(handler) == 0
        assert bool(handler) is True

        logger = logging.getLogger("test_gui_log_handler_bool")
        logger.setLevel(logging.INFO)
        logger.addHandler(handler)
        logger.info("Test log entry")

        assert len(handler) == 1
        assert bool(handler) is True

        handler.clear()
        assert len(handler) == 0
        assert bool(handler) is True


class TestGuiLogHandlerEmit:
    def test_emit_all_standard_levels(self):
        handler = GuiLogHandler(max_entries=10)
        logger = logging.getLogger("test_emit_all_levels")
        logger.setLevel(logging.DEBUG)
        logger.addHandler(handler)

        logger.debug("Debug msg")
        logger.info("Info msg")
        logger.warning("Warn msg")
        logger.error("Error msg")
        logger.critical("Crit msg")

        entries = handler.get_entries()
        levels = [e.level for e in entries]
        assert levels == ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

    def test_emit_timestamp_formatting(self):
        handler = GuiLogHandler()
        logger = logging.getLogger("test_emit_ts")
        logger.setLevel(logging.INFO)
        logger.addHandler(handler)

        logger.info("Timestamp check")
        entries = handler.get_entries()
        assert len(entries) == 1
        assert len(entries[0].timestamp) >= 19  # "YYYY-MM-DD HH:MM:SS"

    def test_emit_string_formatting_args(self):
        handler = GuiLogHandler()
        logger = logging.getLogger("test_emit_args")
        logger.setLevel(logging.INFO)
        logger.addHandler(handler)

        logger.info("Syncing %s: %d bytes", "note.md", 2048)
        entries = handler.get_entries()
        assert len(entries) == 1
        assert entries[0].message == "Syncing note.md: 2048 bytes"

    def test_emit_exception_traceback(self):
        handler = GuiLogHandler()
        logger = logging.getLogger("test_emit_exc")
        logger.setLevel(logging.INFO)
        logger.addHandler(handler)

        try:
            1 / 0
        except ZeroDivisionError:
            logger.exception("Division error occurred")

        entries = handler.get_entries()
        assert len(entries) == 1
        assert "ZeroDivisionError" in entries[0].message
        assert "division by zero" in entries[0].message

    def test_emit_multiline_log(self):
        handler = GuiLogHandler()
        logger = logging.getLogger("test_emit_multiline")
        logger.setLevel(logging.INFO)
        logger.addHandler(handler)

        logger.info("Line 1\nLine 2\nLine 3")
        entries = handler.get_entries()
        assert len(entries) == 1
        assert "Line 1\nLine 2\nLine 3" in entries[0].message


class TestGuiLogHandlerRingBuffer:
    def test_ring_buffer_exact_capacity_1000(self):
        handler = GuiLogHandler(max_entries=1000)
        logger = logging.getLogger("test_ring_exact_1000")
        logger.setLevel(logging.INFO)
        logger.addHandler(handler)

        for i in range(1000):
            logger.info(f"Log {i}")

        assert len(handler.get_entries()) == 1000
        assert len(handler) == 1000

    def test_ring_buffer_evicts_oldest_on_1001st(self):
        handler = GuiLogHandler(max_entries=1000)
        logger = logging.getLogger("test_ring_evict")
        logger.setLevel(logging.INFO)
        logger.addHandler(handler)

        for i in range(1001):
            logger.info(f"Log {i}")

        entries = handler.get_entries()
        assert len(entries) == 1000
        assert entries[0].message == "Log 1"
        assert entries[-1].message == "Log 1000"

    def test_ring_buffer_flood_5000_logs(self):
        handler = GuiLogHandler(max_entries=1000)
        logger = logging.getLogger("test_ring_flood")
        logger.setLevel(logging.INFO)
        logger.addHandler(handler)

        for i in range(5000):
            logger.info(f"Flood line {i}")

        entries = handler.get_entries()
        assert len(entries) == 1000
        assert entries[-1].message == "Flood line 4999"

    def test_ring_buffer_custom_capacity_50(self):
        handler = GuiLogHandler(max_entries=50)
        logger = logging.getLogger("test_ring_custom_50")
        logger.setLevel(logging.INFO)
        logger.addHandler(handler)

        for i in range(70):
            logger.info(f"Line {i}")

        entries = handler.get_entries()
        assert len(entries) == 50
        assert entries[0].message == "Line 20"
        assert entries[-1].message == "Line 69"


class TestGuiLogHandlerLevelFiltering:
    @pytest.fixture
    def populated_handler(self):
        handler = GuiLogHandler(max_entries=100)
        logger = logging.getLogger(f"test_filter_{time.time()}")
        logger.setLevel(logging.DEBUG)
        logger.addHandler(handler)

        logger.debug("Debug event")
        logger.info("Info event")
        logger.warning("Warn event")
        logger.error("Error event")
        logger.critical("Crit event")
        return handler

    def test_filter_exact_match_error(self, populated_handler):
        res = populated_handler.get_entries(level_filter="ERROR")
        assert len(res) == 1
        assert res[0].level == "ERROR"

    def test_filter_exact_match_warning(self, populated_handler):
        res = populated_handler.get_entries(level_filter="WARNING")
        assert len(res) == 1
        assert res[0].level == "WARNING"

    def test_filter_exact_match_info(self, populated_handler):
        res = populated_handler.get_entries(level_filter="INFO")
        assert len(res) == 1
        assert res[0].level == "INFO"

    def test_filter_case_insensitive(self, populated_handler):
        res1 = populated_handler.get_entries(level_filter="error")
        res2 = populated_handler.get_entries(level_filter="Error")
        res3 = populated_handler.get_entries(level_filter="ERROR")
        assert res1 == res2 == res3
        assert len(res1) == 1

    def test_filter_all_or_none(self, populated_handler):
        assert len(populated_handler.get_entries(level_filter="ALL")) == 5
        assert len(populated_handler.get_entries(level_filter=None)) == 5
        assert len(populated_handler.get_entries(level_filter="")) == 5
        assert len(populated_handler.get_entries(level_filter="   ")) == 5

    def test_filter_unknown_level(self, populated_handler):
        assert populated_handler.get_entries(level_filter="UNKNOWN_LVL") == []


class TestGuiLogHandlerSearchQuery:
    @pytest.fixture
    def populated_handler(self):
        handler = GuiLogHandler(max_entries=100)
        logger = logging.getLogger(f"test_search_{time.time()}")
        logger.setLevel(logging.INFO)
        logger.addHandler(handler)

        logger.info("Starting sync on Google Drive vault")
        logger.info("Processing vault Obsidian_Unique_Keyword")
        logger.info("Routine heartbeat")
        return handler

    def test_search_exact_token(self, populated_handler):
        res = populated_handler.get_entries(search_query="Obsidian_Unique_Keyword")
        assert len(res) == 1
        assert "Obsidian_Unique_Keyword" in res[0].message

    def test_search_case_insensitive(self, populated_handler):
        res = populated_handler.get_entries(search_query="google drive")
        assert len(res) == 1
        assert "Google Drive" in res[0].message

    def test_search_substring(self, populated_handler):
        res = populated_handler.get_entries(search_query="heart")
        assert len(res) == 1
        assert "heartbeat" in res[0].message

    def test_search_empty_or_none(self, populated_handler):
        assert len(populated_handler.get_entries(search_query="")) == 3
        assert len(populated_handler.get_entries(search_query=None)) == 3
        assert len(populated_handler.get_entries(search_query="   ")) == 3

    def test_search_no_matches(self, populated_handler):
        assert populated_handler.get_entries(search_query="nonexistent_keyword") == []

    def test_search_matches_level_or_timestamp_or_logger(self):
        handler = GuiLogHandler(max_entries=10)
        entry = LogEntry(
            timestamp="2026-10-03 14:15:16",
            level="WARNING",
            message="Ordinary message",
            logger_name="custom_rclone_bridge",
        )
        with handler._lock:
            handler._buffer.append(entry)

        assert len(handler.get_entries(search_query="rclone_bridge")) == 1
        assert len(handler.get_entries(search_query="WARNING")) == 1
        assert len(handler.get_entries(search_query="14:15:16")) == 1


class TestGuiLogHandlerCombinedFiltering:
    def test_combined_level_and_search(self):
        handler = GuiLogHandler()
        logger = logging.getLogger(f"test_comb_{time.time()}")
        logger.setLevel(logging.DEBUG)
        logger.addHandler(handler)

        logger.info("Timeout occurred on check")
        logger.error("Timeout occurred on transfer")
        logger.error("Connection refused")

        res = handler.get_entries(level_filter="ERROR", search_query="timeout")
        assert len(res) == 1
        assert res[0].level == "ERROR"
        assert "Timeout occurred on transfer" in res[0].message


class TestGuiLogHandlerExport:
    def test_export_creates_file_with_all_entries(self, tmp_path):
        handler = GuiLogHandler()
        logger = logging.getLogger(f"test_exp_{time.time()}")
        logger.setLevel(logging.INFO)
        logger.addHandler(handler)

        logger.info("Line 1")
        logger.warning("Line 2")
        logger.error("Line 3")

        out = tmp_path / "export.log"
        handler.export_to_file(str(out))
        assert out.exists()
        text = out.read_text(encoding="utf-8")
        assert "Line 1" in text
        assert "Line 2" in text
        assert "Line 3" in text

    def test_export_creates_nonexistent_parent_directories(self, tmp_path):
        handler = GuiLogHandler()
        logger = logging.getLogger(f"test_exp_dirs_{time.time()}")
        logger.setLevel(logging.INFO)
        logger.addHandler(handler)
        logger.info("Deep dir log")

        out = tmp_path / "deep" / "nested" / "logs" / "out.log"
        handler.export_to_file(str(out))
        assert out.exists()

    def test_export_utf8_encoding_fidelity(self, tmp_path):
        handler = GuiLogHandler()
        logger = logging.getLogger(f"test_exp_utf8_{time.time()}")
        logger.setLevel(logging.INFO)
        logger.addHandler(handler)
        logger.info("Syncing 📚 Japanese: メモ.md, Spanish: Español, Emojis: ⚡🚀")

        out = tmp_path / "utf8.log"
        handler.export_to_file(str(out))
        read_text = out.read_text(encoding="utf-8")
        assert "メモ.md" in read_text
        assert "Español" in read_text
        assert "⚡🚀" in read_text

    def test_export_overwrites_existing_file(self, tmp_path):
        handler = GuiLogHandler()
        logger = logging.getLogger(f"test_exp_overwrite_{time.time()}")
        logger.setLevel(logging.INFO)
        logger.addHandler(handler)
        logger.info("First run")

        out = tmp_path / "out.log"
        handler.export_to_file(str(out))
        assert "First run" in out.read_text(encoding="utf-8")

        logger.info("Second run")
        handler.export_to_file(str(out))
        assert "Second run" in out.read_text(encoding="utf-8")

    def test_export_empty_handler(self, tmp_path):
        handler = GuiLogHandler()
        out = tmp_path / "empty.log"
        handler.export_to_file(str(out))
        assert out.exists()
        assert out.read_text(encoding="utf-8") == ""

    def test_export_empty_target_raises_value_error(self):
        handler = GuiLogHandler()
        with pytest.raises(ValueError):
            handler.export_to_file("")
        with pytest.raises(ValueError):
            handler.export_to_file("   ")


class TestGuiLogHandlerListeners:
    def test_add_and_remove_listener(self):
        handler = GuiLogHandler()
        received = []
        cb = lambda entry: received.append(entry)

        handler.add_listener(cb)
        assert cb in handler._listeners

        handler.remove_listener(cb)
        assert cb not in handler._listeners

    def test_listener_invoked_on_emit(self):
        handler = GuiLogHandler()
        received = []
        handler.add_listener(lambda entry: received.append(entry))

        logger = logging.getLogger(f"test_listener_invoked_{time.time()}")
        logger.setLevel(logging.INFO)
        logger.addHandler(handler)

        logger.info("Testing listener notification")
        assert len(received) == 1
        assert received[0].message == "Testing listener notification"

    def test_failing_listener_does_not_break_emit(self):
        handler = GuiLogHandler()
        def bad_cb(entry):
            raise RuntimeError("Listener failure")

        handler.add_listener(bad_cb)
        logger = logging.getLogger(f"test_failing_listener_{time.time()}")
        logger.setLevel(logging.INFO)
        logger.addHandler(handler)

        logger.info("Should not crash despite bad listener")
        assert len(handler.get_entries()) == 1


class TestGuiLogHandlerConcurrencyAndLoggerIntegration:
    def test_concurrent_emit_20_threads(self):
        handler = GuiLogHandler(max_entries=500)
        logger = logging.getLogger(f"test_concurrent_emit_{time.time()}")
        logger.setLevel(logging.INFO)
        logger.addHandler(handler)

        barrier = threading.Barrier(20)
        errors = []

        def worker(tid: int):
            try:
                barrier.wait()
                for i in range(50):
                    logger.info(f"Thread {tid} message {i}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        assert len(handler.get_entries()) == 500

    def test_concurrent_emit_and_get_entries(self):
        handler = GuiLogHandler(max_entries=200)
        logger = logging.getLogger(f"test_concurrent_read_write_{time.time()}")
        logger.setLevel(logging.INFO)
        logger.addHandler(handler)

        stop = threading.Event()
        errors = []

        def writer():
            cnt = 0
            while not stop.is_set():
                try:
                    logger.info(f"Log {cnt}")
                    cnt += 1
                except Exception as e:
                    errors.append(e)

        def reader():
            while not stop.is_set():
                try:
                    entries = handler.get_entries(level_filter="INFO", search_query="Log")
                    assert isinstance(entries, list)
                except Exception as e:
                    errors.append(e)

        w_thread = threading.Thread(target=writer)
        r_thread = threading.Thread(target=reader)
        w_thread.start()
        r_thread.start()

        time.sleep(0.1)
        stop.set()
        w_thread.join()
        r_thread.join()

        assert errors == []

    def test_concurrent_emit_and_export(self, tmp_path):
        handler = GuiLogHandler(max_entries=500)
        logger = logging.getLogger(f"test_concurrent_export_{time.time()}")
        logger.setLevel(logging.INFO)
        logger.addHandler(handler)

        stop = threading.Event()
        errors = []

        def writer():
            i = 0
            while not stop.is_set() and i < 200:
                try:
                    logger.info(f"Streaming line {i}")
                    i += 1
                    time.sleep(0.001)
                except Exception as e:
                    errors.append(e)

        t = threading.Thread(target=writer)
        t.start()

        time.sleep(0.02)
        out = tmp_path / "concurrent_export.log"
        handler.export_to_file(str(out))

        stop.set()
        t.join()

        assert errors == []
        assert out.exists()
        content = out.read_text(encoding="utf-8")
        assert "Streaming line" in content

    def test_setup_logger_integration(self):
        reset_gui_log_handler()
        logger = setup_logger("test_app_integration")
        gui_handler = get_gui_log_handler()

        assert any(isinstance(h, GuiLogHandler) for h in logger.handlers)
        logger.info("Application setup message")

        entries = gui_handler.get_entries()
        assert any("Application setup message" in e.message for e in entries)

        # Child logger propagation under 'src'
        child_logger = logging.getLogger("src.core.test_module")
        child_logger.info("Child module message")
        child_entries = gui_handler.get_entries()
        assert any("Child module message" in e.message for e in child_entries)

    def test_reset_gui_log_handler(self):
        h1 = get_gui_log_handler()
        logger = logging.getLogger(f"test_reset_{time.time()}")
        logger.setLevel(logging.INFO)
        logger.addHandler(h1)
        logger.info("Before reset")
        assert len(h1) >= 1

        reset_gui_log_handler()
        h2 = get_gui_log_handler()
        assert h1 is not h2
        assert len(h2) == 0
