"""
Empirical Adversarial Challenge Suite for Milestone 2 Iteration 2.
Evaluates SyncWorker history recording and SyncHistoryManager truthiness:
1. Empty history recording across multiple sequential and concurrent sync runs and statuses.
2. Boolean truthiness of SyncHistoryManager and GuiLogHandler across states (empty, populated, cleared, corrupted).
3. Defensive boundaries and resilience under manager persistence failures.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from unittest.mock import MagicMock


from src.core.config import VaultProfile
from src.core.history_manager import SyncHistoryManager, SyncRunRecord
from src.core.sync_worker import SyncStatus, SyncWorker
from src.utils.log_handler import GuiLogHandler
from tests.builders import vault_config

VAULT = VaultProfile(name="Principal")


class TestEmptyHistoryRecordingLifecycle:
    """Group 1: Tests empty history recording across multiple runs and statuses."""

    def test_sequential_empty_history_recording_across_all_statuses(self, tmp_path):
        """Worker must record all sync statuses when starting with 0 records."""
        hist_file = tmp_path / "sequential_history.json"
        hm = SyncHistoryManager(history_file=hist_file)
        assert len(hm) == 0
        assert bool(hm) is True

        worker = SyncWorker(config=MagicMock(), rclone_manager=MagicMock(), history_manager=hm)

        statuses = [
            ("SUCCESS", 1.1, ["note1.md"], 100, None),
            ("ERROR", 0.5, [], 0, "Network timeout"),
            ("CONFLICT", 2.4, ["conflict.md"], 500, "Conflict detected"),
            ("PARTIAL", 3.0, ["part1.md", "part2.md"], 1500, "User cancelled"),
            ("SUCCESS", 1.8, ["note2.md"], 200, None),
            ("ERROR", 0.9, [], 0, "Auth failed"),
            ("CONFLICT", 1.5, ["c2.md"], 400, "Conflict"),
            ("PARTIAL", 2.2, ["p3.md"], 800, "Interrupted"),
            ("SUCCESS", 0.8, ["note3.md"], 300, None),
            ("SUCCESS", 0.4, [], 0, None),
        ]

        for i, (st, dur, files, b_trans, err) in enumerate(statuses, start=1):
            rec = worker._record_sync_history(VAULT, st, dur, files, b_trans, err)
            assert rec is not None, f"Run {i} returned None for status {st}"
            assert rec.status == st
            assert rec.duration_seconds == dur
            assert rec.files_transferred == files
            assert rec.bytes_transferred == b_trans
            assert rec.error_message == err
            assert len(hm) == i, f"Expected {i} records in manager, got {len(hm)}"

        # Assert disk persistence
        assert hist_file.exists()
        disk_records = json.loads(hist_file.read_text(encoding="utf-8"))
        assert len(disk_records) == len(statuses)

        # Assert reverse-chronological ordering
        recent = hm.get_recent_runs(limit=20)
        assert len(recent) == len(statuses)
        expected_statuses = [s[0] for s in reversed(statuses)]
        assert [r.status for r in recent] == expected_statuses

    def test_empty_history_with_clear_history_interleaved(self, tmp_path):
        """History recording must survive and work after clear_history resets to 0."""
        hist_file = tmp_path / "interleaved_clear.json"
        hm = SyncHistoryManager(history_file=hist_file)
        worker = SyncWorker(config=MagicMock(), rclone_manager=MagicMock(), history_manager=hm)

        assert len(hm) == 0
        assert bool(hm) is True

        # Phase 1: Record 3 runs
        for i in range(3):
            rec = worker._record_sync_history(VAULT, "SUCCESS", 1.0, [f"f_{i}.md"])
            assert rec is not None
        assert len(hm) == 3

        # Phase 2: Clear history
        hm.clear_history()
        assert len(hm) == 0
        assert bool(hm) is True
        assert json.loads(hist_file.read_text(encoding="utf-8")) == []

        # Phase 3: Record immediately following clear
        rec_post_clear = worker._record_sync_history(VAULT, "SUCCESS", 2.0, ["after_clear.md"])
        assert rec_post_clear is not None
        assert len(hm) == 1
        assert bool(hm) is True

        reloaded = SyncHistoryManager(history_file=hist_file)
        assert len(reloaded) == 1
        assert reloaded.get_recent_runs()[0].files_transferred == ["after_clear.md"]

    def test_concurrent_sync_history_recording_from_empty_state(self, tmp_path):
        """Multiple threads concurrently recording through SyncWorker from initially empty state."""
        hist_file = tmp_path / "concurrent_worker_history.json"
        hm = SyncHistoryManager(history_file=hist_file, max_records=100)
        worker = SyncWorker(config=MagicMock(), rclone_manager=MagicMock(), history_manager=hm)

        assert len(hm) == 0
        num_threads = 10
        runs_per_thread = 20
        barrier = threading.Barrier(num_threads)
        errors: list[Exception] = []

        def worker_task(thread_id: int):
            try:
                barrier.wait(timeout=5.0)
                statuses = ["SUCCESS", "ERROR", "CONFLICT", "PARTIAL"]
                for i in range(runs_per_thread):
                    status = statuses[(thread_id + i) % 4]
                    rec = worker._record_sync_history(
                        VAULT,
                        status=status,
                        duration=float(i) * 0.1,
                        files_transferred=[f"t{thread_id}_f{i}.md"],
                        bytes_transferred=i * 10,
                        error_message="Err" if status == "ERROR" else None,
                    )
                    assert rec is not None
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker_task, args=(t,)) for t in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10.0)

        assert not any(t.is_alive() for t in threads), "Threads timed out"
        assert errors == [], f"Thread errors: {errors}"
        # Ring buffer caps at 100
        assert len(hm) == 100
        assert hist_file.exists()
        disk_data = json.loads(hist_file.read_text(encoding="utf-8"))
        assert len(disk_data) == 100

    def test_execute_sync_presync_validation_errors_recorded_when_initially_empty(self, tmp_path):
        """_execute_sync pre-sync validation failures record ERROR history when empty."""
        hist_file = tmp_path / "presync_err_history.json"
        hm = SyncHistoryManager(history_file=hist_file)
        assert len(hm) == 0

        # Subcase A: Missing vault path
        cfg = vault_config("")
        worker = SyncWorker(config=cfg, rclone_manager=MagicMock(), history_manager=hm)
        ok = worker._execute_sync()
        assert ok is False
        assert len(hm) == 1
        rec1 = hm.get_recent_runs()[0]
        assert rec1.status == "ERROR"
        assert "no configurada" in (rec1.error_message or "")

        # Subcase B: Non-existent vault directory
        cfg.active_vault.local_path = str(tmp_path / "nonexistent_dir_12345")
        ok = worker._execute_sync()
        assert ok is False
        assert len(hm) == 2
        rec2 = hm.get_recent_runs()[0]
        assert rec2.status == "ERROR"
        assert "no existe" in (rec2.error_message or "")


class TestBooleanTruthinessSemantics:
    """Group 2: Tests boolean truthiness across SyncHistoryManager and GuiLogHandler."""

    def test_sync_history_manager_truthiness_matrix(self, tmp_path):
        """SyncHistoryManager must evaluate to True in all empty, populated, and cleared states."""
        # 1. Non-existent file
        hm = SyncHistoryManager(history_file=tmp_path / "nonexistent.json")
        assert len(hm) == 0
        assert bool(hm) is True
        assert (True if hm else False) is True
        assert (True if not hm else False) is False

        # 2. Existing empty file
        empty_file = tmp_path / "empty.json"
        empty_file.write_text("[]", encoding="utf-8")
        hm2 = SyncHistoryManager(history_file=empty_file)
        assert len(hm2) == 0
        assert bool(hm2) is True

        # 3. Corrupted file recovered
        corrupt_file = tmp_path / "corrupt.json"
        corrupt_file.write_text("{bad json: true", encoding="utf-8")
        hm3 = SyncHistoryManager(history_file=corrupt_file)
        assert len(hm3) == 0
        assert bool(hm3) is True

        # 4. Populated manager
        rec = SyncRunRecord("r1", "2026-10-03T10:00:00Z", "Vault", "SUCCESS", 1.0)
        hm.record_run(rec)
        assert len(hm) == 1
        assert bool(hm) is True
        assert (True if hm else False) is True

        # 5. Cleared manager
        hm.clear_history()
        assert len(hm) == 0
        assert bool(hm) is True
        assert (True if hm else False) is True
        assert (True if not hm else False) is False

        # 6. Compound boolean logic
        assert (hm and "valid") == "valid"
        assert (not hm or "fallback") == "fallback"

    def test_gui_log_handler_truthiness_matrix(self):
        """GuiLogHandler must evaluate to True in empty, populated, and drained states."""
        glh = GuiLogHandler()
        assert len(glh) == 0
        assert bool(glh) is True
        assert (True if glh else False) is True
        assert (True if not glh else False) is False

        # Populated
        import logging
        record = logging.LogRecord("test", logging.INFO, "test.py", 1, "msg", (), None)
        glh.emit(record)
        assert len(glh) == 1
        assert bool(glh) is True

        # Logical operations
        assert (glh and 42) == 42
        assert (not glh or "expected") == "expected"


class TestDefensiveBoundariesAndResilience:
    """Group 3: Tests exception suppression and argument coercion."""

    def test_record_sync_history_catches_manager_exceptions(self):
        """Exceptions thrown inside history_manager.record_run are swallowed without disrupting worker."""
        broken_hm = MagicMock()
        broken_hm.record_run.side_effect = IOError("Disk full or permission denied")

        worker = SyncWorker(config=MagicMock(), rclone_manager=MagicMock(), history_manager=broken_hm)
        res = worker._record_sync_history(VAULT, "SUCCESS", 1.0, ["file.md"])

        assert res is None, "Expected None return when manager throws"
        broken_hm.record_run.assert_called_once()

    def test_record_sync_history_coerces_defensive_parameters(self, tmp_path):
        """Negative durations, case-folding of status, and collection coercion."""
        hist_file = tmp_path / "coercion_history.json"
        hm = SyncHistoryManager(history_file=hist_file)
        worker = SyncWorker(config=MagicMock(), rclone_manager=MagicMock(), history_manager=hm)

        # 1. Negative duration clamped to 0.0
        r1 = worker._record_sync_history(VAULT, "success", -5.5, ("file_a.md", "file_b.md"), 100)
        assert r1.status == "SUCCESS"
        assert r1.duration_seconds == 0.0
        assert r1.files_transferred == ["file_a.md", "file_b.md"]

        # 2. None files_transferred coerced to []
        r2 = worker._record_sync_history(VAULT, "error", 2.0, None)
        assert r2.status == "ERROR"
        assert r2.files_transferred == []

        # 3. Large duration and large byte count
        r3 = worker._record_sync_history(VAULT, "PARTIAL", 86400.123, ["huge.iso"], 10**11)
        assert r3.duration_seconds == 86400.12
        assert r3.bytes_transferred == 10**11

    def test_high_volume_sync_runs_ring_buffer_eviction(self, tmp_path):
        """Ring buffer correctly evicts oldest runs under high volume churn via worker."""
        hist_file = tmp_path / "churn_history.json"
        hm = SyncHistoryManager(history_file=hist_file, max_records=25)
        worker = SyncWorker(config=MagicMock(), rclone_manager=MagicMock(), history_manager=hm)

        assert len(hm) == 0
        for i in range(100):
            rec = worker._record_sync_history(
                VAULT,
                status="SUCCESS",
                duration=float(i) * 0.05,
                files_transferred=[f"churn_{i}.md"],
            )
            assert rec is not None

        assert len(hm) == 25
        assert hist_file.exists()
        disk_data = json.loads(hist_file.read_text(encoding="utf-8"))
        assert len(disk_data) == 25
        # Most recent run was i=99, oldest in window is i=75
        recent = hm.get_recent_runs(limit=25)
        assert recent[0].files_transferred == ["churn_99.md"]
        assert recent[-1].files_transferred == ["churn_75.md"]

    def test_concurrent_clear_and_record_race(self, tmp_path):
        """Concurrent threads calling _record_sync_history while another thread calls clear_history."""
        hist_file = tmp_path / "race_clear_history.json"
        hm = SyncHistoryManager(history_file=hist_file, max_records=50)
        worker = SyncWorker(config=MagicMock(), rclone_manager=MagicMock(), history_manager=hm)

        stop_event = threading.Event()
        errors: list[Exception] = []

        def recorder(idx: int):
            try:
                for j in range(30):
                    if stop_event.is_set():
                        break
                    worker._record_sync_history(VAULT, "SUCCESS", 0.1, [f"rec_{idx}_{j}.md"])
            except Exception as e:
                errors.append(e)

        def clearer():
            try:
                for _ in range(10):
                    if stop_event.is_set():
                        break
                    hm.clear_history()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=recorder, args=(i,)) for i in range(5)]
        clear_thread = threading.Thread(target=clearer)

        for t in threads:
            t.start()
        clear_thread.start()

        for t in threads:
            t.join(timeout=10.0)
        clear_thread.join(timeout=10.0)

        assert errors == [], f"Errors during concurrent clear/record race: {errors}"
        # Validate file on disk is valid JSON
        assert hist_file.exists()
        content = hist_file.read_text(encoding="utf-8")
        parsed = json.loads(content)
        assert isinstance(parsed, list)

    def test_massive_payload_and_huge_error_message(self, tmp_path):
        """Worker records and serializes huge file lists and large error messages without corruption."""
        hist_file = tmp_path / "massive_payload.json"
        hm = SyncHistoryManager(history_file=hist_file)
        worker = SyncWorker(config=MagicMock(), rclone_manager=MagicMock(), history_manager=hm)

        massive_files = [f"path/to/nested/subfolder/document_{i}.markdown" for i in range(2000)]
        huge_error = "FATAL ERROR: " + ("A" * 100000)

        rec = worker._record_sync_history(
            VAULT,
            status="ERROR",
            duration=45.67,
            files_transferred=massive_files,
            bytes_transferred=1024**3,
            error_message=huge_error,
        )

        assert rec is not None
        assert len(rec.files_transferred) == 2000
        assert rec.error_message == huge_error
        assert len(hm) == 1

        # Re-read from disk to guarantee persistence fidelity
        reloaded = SyncHistoryManager(history_file=hist_file)
        loaded_rec = reloaded.get_recent_runs()[0]
        assert len(loaded_rec.files_transferred) == 2000
        assert loaded_rec.error_message == huge_error
        assert loaded_rec.bytes_transferred == 1024**3
