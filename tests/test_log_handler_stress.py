"""
Empirical Adversarial Stress Test Suite for GuiLogHandler and Logger Integration.
Focuses on:
1. High-volume concurrent log flooding (10 threads, 50,000 log records).
2. Stress concurrent emit, read, clear, and atomic export (zero deque mutation errors, zero deadlocks).
3. Malformed and adversarial search queries (regex characters, 1MB strings, null bytes, non-strings).
4. Boundary and invalid level filters (case variations, aliases, whitespace, non-strings).
5. File export failure modes, permission boundaries, and temporary file (.tmp) cleanup.
6. Listener re-entrancy, mutation, and exception isolation.
7. Concurrent logger setup and handler resets.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
import stat
import sys
import tempfile
import threading
import time
import tracemalloc
from typing import List
import pytest

from src.utils.log_handler import GuiLogHandler, LogEntry
from src.utils.logger import (
    get_gui_log_handler,
    reset_gui_log_handler,
    setup_logger,
)


class TestHighVolumeLogFlood:
    """Stress Scenario 1: High-Volume Log Flood."""

    def test_flood_10_threads_50k_logs_bounded_memory(self):
        """
        Spawn 10 concurrent producer threads emitting 5,000 logs each (50,000 total).
        Verify memory remains bounded, buffer len == 1000, zero dropped locks or deadlocks.
        """
        tracemalloc.start()
        handler = GuiLogHandler(max_entries=1000)
        logger = logging.getLogger("stress_flood_50k")
        logger.setLevel(logging.INFO)
        logger.propagate = False  # Avoid pytest capture buffer accumulating 50,000 LogRecords
        logger.addHandler(handler)

        num_threads = 10
        logs_per_thread = 5000
        total_logs = num_threads * logs_per_thread

        barrier = threading.Barrier(num_threads)
        errors: List[Exception] = []

        def worker(tid: int):
            try:
                barrier.wait(timeout=5.0)
                for i in range(logs_per_thread):
                    logger.info(f"Worker {tid} - record {i}: synchronization payload benchmark data")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(num_threads)]

        start_time = time.perf_counter()
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15.0)
            assert not t.is_alive(), f"Thread timed out! Potential deadlock."
        elapsed = time.perf_counter() - start_time

        current_mem, peak_mem = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        # 1. Zero thread errors
        assert errors == [], f"Encountered producer thread errors: {errors}"

        # 2. Bounded capacity verification
        entries = handler.get_entries()
        assert len(handler) == 1000
        assert len(entries) == 1000

        # 3. Throughput verification (> 10,000 logs/sec expected on modern hardware)
        throughput = total_logs / elapsed
        assert throughput > 3500, f"Logging throughput too low: {throughput:.1f} logs/sec"

        # 4. Memory footprint verification (peak < 10MB)
        assert peak_mem < 10 * 1024 * 1024, f"Memory leak detected: peak {peak_mem / 1024 / 1024:.2f} MB"

        # 5. Entry integrity verification
        for entry in entries:
            assert entry.level == "INFO"
            assert entry.timestamp and len(entry.timestamp) >= 19
            assert "Worker " in entry.message


class TestConcurrentMutationAndExport:
    """Stress Scenario 2: Concurrent Mutation & Export."""

    def test_concurrent_emit_export_and_reads(self, tmp_path):
        """
        Simultaneously run:
        - 8 producer threads emitting logs continuously (40,000 logs)
        - 2 reader threads querying get_entries with search/filters
        - 2 exporter threads repeatedly calling export_to_file
        - 1 listener subscriber churn thread
        Verify zero deque mutation errors, zero deadlocks, and valid exported files.
        """
        handler = GuiLogHandler(max_entries=1000)
        logger = logging.getLogger(f"stress_concurrent_{time.time()}")
        logger.setLevel(logging.INFO)
        logger.propagate = False
        logger.addHandler(handler)

        stop_event = threading.Event()
        exporters_done_event = threading.Event()
        errors: List[tuple] = []
        export_counts = [0, 0]

        # 8 Producer threads: emit continuously until exporters finish
        def producer(tid: int):
            i = 0
            while not exporters_done_event.is_set():
                try:
                    logger.info(f"Prod-{tid} log-{i} concurrent content")
                    i += 1
                except Exception as e:
                    errors.append(("producer", tid, e))
                    break

        # 2 Reader threads
        def reader(rid: int):
            while not exporters_done_event.is_set():
                try:
                    res = handler.get_entries(level_filter="INFO", search_query=f"Prod-{rid}")
                    assert isinstance(res, list)
                    time.sleep(0.001)
                except Exception as e:
                    errors.append(("reader", rid, e))
                    break

        # 2 Exporter threads: each performs 10 exports
        def exporter(eid: int):
            idx = 0
            while idx < 10 and not stop_event.is_set():
                out_file = tmp_path / f"export_{eid}_{idx}.log"
                try:
                    handler.export_to_file(out_file)
                    export_counts[eid] += 1
                    assert out_file.exists()
                    text = out_file.read_text(encoding="utf-8")
                    for line in text.splitlines():
                        assert "[" in line and "]" in line
                    idx += 1
                    time.sleep(0.002)
                except Exception as e:
                    errors.append(("exporter", eid, e))
                    break

        # 1 Listener churn thread
        def listener_worker():
            def cb(e: LogEntry):
                pass
            while not exporters_done_event.is_set():
                try:
                    handler.add_listener(cb)
                    time.sleep(0.001)
                    handler.remove_listener(cb)
                    time.sleep(0.001)
                except Exception as e:
                    errors.append(("listener", 0, e))
                    break

        producers = [threading.Thread(target=producer, args=(i,)) for i in range(8)]
        readers = [threading.Thread(target=reader, args=(i,)) for i in range(2)]
        exporters = [threading.Thread(target=exporter, args=(i,)) for i in range(2)]
        listener_t = threading.Thread(target=listener_worker)

        all_threads = producers + readers + exporters + [listener_t]
        for t in all_threads:
            t.start()

        # Wait for both exporters to finish their 10 exports
        for e in exporters:
            e.join(timeout=15.0)
            assert not e.is_alive(), "Exporter deadlock detected!"

        # Signal all other threads to finish
        exporters_done_event.set()
        stop_event.set()

        for p in producers:
            p.join(timeout=10.0)
            assert not p.is_alive(), "Producer deadlock detected!"

        for t in readers + [listener_t]:
            t.join(timeout=5.0)
            assert not t.is_alive(), "Worker deadlock detected!"

        # Verify zero leftover .tmp files
        tmp_files = list(tmp_path.glob(".*.tmp"))
        assert len(tmp_files) == 0, f"Found lingering temporary files: {tmp_files}"

        # Verify no thread errors
        assert errors == [], f"Thread errors encountered: {errors}"
        assert export_counts == [10, 10], f"Expected 10 exports each, got: {export_counts}"

    def test_concurrent_export_to_same_file(self, tmp_path):
        """
        Multiple threads concurrently export to the EXACT same destination file.
        Verify atomic replace prevents file corruption, collisions, or crashes.
        """
        handler = GuiLogHandler(max_entries=500)
        logger = logging.getLogger("stress_same_file_export")
        logger.setLevel(logging.INFO)
        logger.addHandler(handler)

        target_file = tmp_path / "shared_export.log"
        num_threads = 6
        barrier = threading.Barrier(num_threads)
        errors: List[Exception] = []

        def worker(tid: int):
            try:
                barrier.wait(timeout=5.0)
                for i in range(15):
                    logger.info(f"Writer {tid} iteration {i}")
                    handler.export_to_file(target_file)
                    # Verify readable and valid at all times
                    assert target_file.exists()
                    content = target_file.read_text(encoding="utf-8")
                    assert len(content) > 0
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10.0)
            assert not t.is_alive()

        assert errors == [], f"Errors during same-file export: {errors}"
        assert list(tmp_path.glob(".*.tmp")) == []
        assert target_file.exists()

    def test_concurrent_clear_during_export_and_emit(self, tmp_path):
        """
        Test calling clear() concurrently with emit() and export_to_file().
        Verify no exceptions and buffer remains valid.
        """
        handler = GuiLogHandler(max_entries=500)
        logger = logging.getLogger("stress_clear_export")
        logger.setLevel(logging.INFO)
        logger.addHandler(handler)

        stop_event = threading.Event()
        errors: List[Exception] = []

        def emitter():
            i = 0
            while not stop_event.is_set():
                try:
                    logger.info(f"Message {i}")
                    i += 1
                except Exception as e:
                    errors.append(e)

        def exporter():
            while not stop_event.is_set():
                try:
                    handler.export_to_file(tmp_path / "clear_test.log")
                    time.sleep(0.001)
                except Exception as e:
                    errors.append(e)

        def cleaner():
            while not stop_event.is_set():
                try:
                    handler.clear()
                    time.sleep(0.002)
                except Exception as e:
                    errors.append(e)

        threads = [
            threading.Thread(target=emitter),
            threading.Thread(target=exporter),
            threading.Thread(target=cleaner),
        ]
        for t in threads:
            t.start()

        time.sleep(0.2)
        stop_event.set()
        for t in threads:
            t.join(timeout=5.0)
            assert not t.is_alive()

        assert errors == []


class TestMalformedAndAdversarialSearch:
    """Stress Scenario 3: Malformed Inputs & Search Queries."""

    @pytest.fixture
    def populated_handler(self):
        handler = GuiLogHandler(max_entries=100)
        logger = logging.getLogger(f"adversarial_search_{time.time()}")
        logger.setLevel(logging.DEBUG)
        logger.addHandler(handler)

        logger.info("Literal regex pattern: .*+?[]^$(){}|\\ in log message")
        logger.warning("Special tokens: (?P<name>[a-z]+) and \\d{3}-\\d{4}")
        logger.error("Null byte in message: start\x00middle\x00end")
        logger.debug("Unicode test: 日本語 ⚡🚀 éàç ñ ü and RTL: עִבְרִית")
        logger.info("Control characters: \x1b[31mRed\x1b[0m and \r\n Carriage Return")
        logger.info("Standard informative sync line for baseline")
        return handler

    def test_search_regex_special_characters_treated_as_literals(self, populated_handler):
        """Verify regex special characters do not cause RegexError or unexpected pattern matches."""
        # Exact literal substrings
        assert len(populated_handler.get_entries(search_query=".*+?[]^$(){}|\\")) == 1
        assert len(populated_handler.get_entries(search_query=".*")) == 1
        assert len(populated_handler.get_entries(search_query="[a-z]+")) == 1
        assert len(populated_handler.get_entries(search_query="(?P<name>")) == 1
        assert len(populated_handler.get_entries(search_query="\\d{3}")) == 1
        assert len(populated_handler.get_entries(search_query="^$")) == 1

        # Non-matching regex strings
        assert len(populated_handler.get_entries(search_query=".*[0-9]{5}.*")) == 0
        assert len(populated_handler.get_entries(search_query="[XYZ]{3}")) == 0

    def test_search_null_bytes(self, populated_handler):
        """Verify null bytes in search query match properly without truncation."""
        res = populated_handler.get_entries(search_query="\x00")
        assert len(res) == 1
        assert "start\x00middle\x00end" in res[0].message

        res_full = populated_handler.get_entries(search_query="start\x00middle")
        assert len(res_full) == 1

    def test_search_massive_1mb_string(self, populated_handler):
        """Verify 1MB search query does not hang or raise MemoryError / RecursionError."""
        massive_needle = "A" * (1024 * 1024)
        t0 = time.perf_counter()
        res = populated_handler.get_entries(search_query=massive_needle)
        elapsed = time.perf_counter() - t0

        assert res == []
        assert elapsed < 0.1, f"Search took too long: {elapsed:.3f}s"

    def test_search_in_massive_log_message(self):
        """Verify searching within a massive 1MB log message works efficiently."""
        handler = GuiLogHandler(max_entries=10)
        logger = logging.getLogger("massive_msg_logger")
        logger.setLevel(logging.INFO)
        logger.addHandler(handler)

        giant_body = "A" * 500_000 + "UNIQUE_NEEDLE_42" + "B" * 500_000
        logger.info(giant_body)

        res = handler.get_entries(search_query="unique_needle_42")
        assert len(res) == 1
        assert len(res[0].message) > 1_000_000

    def test_search_ansi_and_unicode_tokens(self, populated_handler):
        """Verify searching ANSI sequences and international scripts."""
        assert len(populated_handler.get_entries(search_query="[31mred")) == 1
        assert len(populated_handler.get_entries(search_query="日本語")) == 1
        assert len(populated_handler.get_entries(search_query="⚡🚀")) == 1
        assert len(populated_handler.get_entries(search_query="עִבְרִית")) == 1

    def test_search_whitespace_and_empty(self, populated_handler):
        """Verify whitespace-only or empty queries return all entries."""
        total = len(populated_handler)
        assert len(populated_handler.get_entries(search_query="")) == total
        assert len(populated_handler.get_entries(search_query="   ")) == total
        assert len(populated_handler.get_entries(search_query="\t\n\r")) == total
        assert len(populated_handler.get_entries(search_query=None)) == total

    def test_search_non_string_types_behavior(self, populated_handler):
        """
        Verify behavior when non-string type is supplied to search_query.
        Since signature specifies Optional[str], non-string types without strip() raise AttributeError.
        """
        with pytest.raises(AttributeError):
            populated_handler.get_entries(search_query=12345)  # type: ignore

        with pytest.raises(AttributeError):
            populated_handler.get_entries(search_query=["query"])  # type: ignore

        with pytest.raises(AttributeError):
            populated_handler.get_entries(search_query=True)  # type: ignore


class TestAdversarialLevelFiltering:
    """Stress Scenario 3 (Part B): Boundary & Invalid Level Filters."""

    @pytest.fixture
    def multi_level_handler(self):
        handler = GuiLogHandler(max_entries=50)
        logger = logging.getLogger(f"adv_levels_{time.time()}")
        logger.setLevel(logging.DEBUG)
        logger.addHandler(handler)

        logger.debug("Debug event")
        logger.info("Info event")
        logger.warning("Warning event")
        logger.error("Error event")
        logger.critical("Critical event")
        return handler

    @pytest.mark.parametrize("level, expected_count, expected_name", [
        ("INFO", 1, "INFO"),
        ("info", 1, "INFO"),
        ("InFo", 1, "INFO"),
        ("  info  ", 1, "INFO"),
        ("WARNING", 1, "WARNING"),
        ("WARN", 1, "WARNING"),
        ("warn", 1, "WARNING"),
        ("ERROR", 1, "ERROR"),
        ("ERR", 1, "ERROR"),
        ("err", 1, "ERROR"),
        ("DEBUG", 1, "DEBUG"),
        ("debug", 1, "DEBUG"),
        ("CRITICAL", 1, "CRITICAL"),
        ("critical", 1, "CRITICAL"),
    ])
    def test_standard_and_aliased_levels(self, multi_level_handler, level, expected_count, expected_name):
        res = multi_level_handler.get_entries(level_filter=level)
        assert len(res) == expected_count
        assert res[0].level == expected_name

    @pytest.mark.parametrize("all_filter", ["ALL", "all", "All", "", "   ", "\t\n", None])
    def test_all_and_empty_filters(self, multi_level_handler, all_filter):
        res = multi_level_handler.get_entries(level_filter=all_filter)
        assert len(res) == 5

    @pytest.mark.parametrize("invalid_level", [
        "UNKNOWN",
        "FATAL",
        "NOTICE",
        "INFO.*",
        "[INFO]",
        "123",
        "INFO\x00",
        "X" * 1000,
    ])
    def test_invalid_and_adversarial_levels_return_empty(self, multi_level_handler, invalid_level):
        res = multi_level_handler.get_entries(level_filter=invalid_level)
        assert res == []

    def test_level_filter_non_string_behavior(self, multi_level_handler):
        """
        Verify behavior when integer level constants (e.g. logging.INFO=20) are passed.
        Raises AttributeError because strip() is expected.
        """
        with pytest.raises(AttributeError):
            multi_level_handler.get_entries(level_filter=logging.INFO)  # type: ignore

        with pytest.raises(AttributeError):
            multi_level_handler.get_entries(level_filter=20)  # type: ignore


class TestExportErrorHandlingAndCleanup:
    """Stress Scenario 4: Export Failures & Temp File Cleanup."""

    def test_export_empty_target_raises_value_error(self):
        handler = GuiLogHandler()
        with pytest.raises(ValueError, match="Target path must not be empty"):
            handler.export_to_file("")
        with pytest.raises(ValueError, match="Target path must not be empty"):
            handler.export_to_file("   ")
        with pytest.raises(ValueError, match="Target path must not be empty"):
            handler.export_to_file(None)  # type: ignore

    def test_export_target_is_existing_directory_fails_cleanly(self, tmp_path):
        """When destination is an existing directory, raises error and cleans up .tmp file."""
        handler = GuiLogHandler()
        logger = logging.getLogger("export_dir_test")
        logger.setLevel(logging.INFO)
        logger.addHandler(handler)
        logger.info("Test payload")

        target_dir = tmp_path / "already_a_dir"
        target_dir.mkdir()

        with pytest.raises((IsADirectoryError, PermissionError, OSError)):
            handler.export_to_file(target_dir)

        # Verify no .tmp file left behind in tmp_path or target_dir
        assert list(tmp_path.glob(".*.tmp")) == []
        assert list(target_dir.glob(".*.tmp")) == []

    def test_export_target_in_readonly_directory(self, tmp_path):
        """When parent directory has no write permissions, fails and cleans up .tmp file."""
        handler = GuiLogHandler()
        logger = logging.getLogger("export_ro_test")
        logger.setLevel(logging.INFO)
        logger.addHandler(handler)
        logger.info("Test payload")

        ro_dir = tmp_path / "readonly_dir"
        ro_dir.mkdir()
        # Drop write permission
        os.chmod(ro_dir, stat.S_IRUSR | stat.S_IXUSR)

        try:
            target_file = ro_dir / "output.log"
            with pytest.raises(PermissionError):
                handler.export_to_file(target_file)

            # Check no .tmp file left behind
            os.chmod(ro_dir, stat.S_IRWXU)
            assert list(ro_dir.glob(".*.tmp")) == []
        finally:
            os.chmod(ro_dir, stat.S_IRWXU)

    def test_export_target_parent_is_a_file(self, tmp_path):
        """When parent path component is a regular file, raises FileExistsError or NotADirectoryError."""
        handler = GuiLogHandler()
        file_parent = tmp_path / "parent_file"
        file_parent.write_text("not a directory")

        target = file_parent / "output.log"
        with pytest.raises((FileExistsError, NotADirectoryError, OSError)):
            handler.export_to_file(target)

        assert list(tmp_path.glob(".*.tmp")) == []

    def test_export_path_with_null_byte(self):
        """Paths with embedded null bytes raise ValueError or TypeError."""
        handler = GuiLogHandler()
        with pytest.raises((ValueError, TypeError)):
            handler.export_to_file("/tmp/log_\x00_file.log")

    def test_export_unwritable_system_path(self):
        """Exporting to protected system paths raises PermissionError."""
        handler = GuiLogHandler()
        with pytest.raises((PermissionError, OSError)):
            handler.export_to_file("/root/system_test_export_never_allowed.log")

    def test_export_deep_parent_directories_auto_created(self, tmp_path):
        """Exporting to deeply nested non-existent directory auto-creates parents."""
        handler = GuiLogHandler()
        logger = logging.getLogger("export_deep_test")
        logger.setLevel(logging.INFO)
        logger.addHandler(handler)
        logger.info("Deep nesting test")

        deep_target = tmp_path / "a" / "b" / "c" / "d" / "e" / "f" / "test.log"
        handler.export_to_file(deep_target)

        assert deep_target.exists()
        assert "Deep nesting test" in deep_target.read_text(encoding="utf-8")

    def test_export_file_permissions_posix(self, tmp_path):
        """On POSIX systems, verify exported file permissions are 0o600."""
        if sys.platform.startswith("win"):
            pytest.skip("POSIX permissions not applicable on Windows")

        handler = GuiLogHandler()
        logger = logging.getLogger("export_perm_test")
        logger.setLevel(logging.INFO)
        logger.addHandler(handler)
        logger.info("Secure content")

        target = tmp_path / "secure.log"
        handler.export_to_file(target)

        file_stat = target.stat()
        file_mode = stat.S_IMODE(file_stat.st_mode)
        assert file_mode == 0o600, f"Expected 0o600, got {oct(file_mode)}"


class TestListenerIsolationAndReentrancy:
    """Stress tests on listener callback safety and isolation."""

    def test_listener_queries_handler_without_deadlock(self):
        """A listener callback that calls handler.get_entries() must not deadlock."""
        handler = GuiLogHandler()
        query_results = []

        def reentrant_listener(entry: LogEntry):
            entries = handler.get_entries()
            query_results.append(len(entries))

        handler.add_listener(reentrant_listener)

        logger = logging.getLogger(f"listener_reentrant_{time.time()}")
        logger.setLevel(logging.INFO)
        logger.addHandler(handler)

        logger.info("Message 1")
        logger.info("Message 2")

        assert len(query_results) == 2
        assert query_results == [1, 2]

    def test_listener_removes_itself_during_callback(self):
        """A listener that unregisters itself during callback must not break iteration."""
        handler = GuiLogHandler()

        def self_removing_listener(entry: LogEntry):
            handler.remove_listener(self_removing_listener)

        handler.add_listener(self_removing_listener)

        logger = logging.getLogger(f"listener_self_remove_{time.time()}")
        logger.setLevel(logging.INFO)
        logger.addHandler(handler)

        logger.info("First call removes")
        assert self_removing_listener not in handler._listeners
        logger.info("Second call proceeds normally")
        assert len(handler.get_entries()) == 2

    def test_listener_raising_exception_does_not_halt_emit(self):
        """An unhandled exception in a listener must be caught and ignored."""
        handler = GuiLogHandler()

        def broken_listener(entry: LogEntry):
            raise RuntimeError("Fatal explosion in listener")

        handler.add_listener(broken_listener)

        logger = logging.getLogger(f"listener_broken_{time.time()}")
        logger.setLevel(logging.INFO)
        logger.addHandler(handler)

        logger.info("Safe emission")
        assert len(handler.get_entries()) == 1


class TestConcurrentLoggerSetupAndReset:
    """Stress testing singleton logger wiring."""

    def test_concurrent_setup_logger_idempotence(self):
        """Calling setup_logger concurrently from multiple threads yields single handler."""
        reset_gui_log_handler()
        num_threads = 10
        barrier = threading.Barrier(num_threads)
        errors = []

        def worker(tid: int):
            try:
                barrier.wait(timeout=5.0)
                setup_logger("obsidian_sync")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)
            assert not t.is_alive()

        assert errors == []
        logger = logging.getLogger("obsidian_sync")
        handlers = [h for h in logger.handlers if isinstance(h, GuiLogHandler)]
        assert len(handlers) == 1

    def test_reset_during_logging_activity(self):
        """Calling reset_gui_log_handler() while threads are actively logging does not crash."""
        reset_gui_log_handler()
        logger = setup_logger("stress_reset_logger")
        stop_event = threading.Event()
        errors = []

        def logging_worker():
            i = 0
            while not stop_event.is_set():
                try:
                    logger.info(f"Log event {i}")
                    i += 1
                except Exception as e:
                    errors.append(e)

        t = threading.Thread(target=logging_worker)
        t.start()

        time.sleep(0.02)
        reset_gui_log_handler()
        time.sleep(0.02)

        stop_event.set()
        t.join(timeout=5.0)
        assert not t.is_alive()
        assert errors == []
