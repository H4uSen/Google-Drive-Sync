"""
Empirical Adversarial Challenge Suite for Milestone 2 Iteration 2.
Evaluates SyncWorker history recording and SyncHistoryManager truthiness:
1. Empty history recording across multiple sequential and concurrent sync runs and statuses.
2. Boolean truthiness of SyncHistoryManager and GuiLogHandler across states (empty, populated, cleared, corrupted).
3. Config mock and None edge cases (None, MagicMock, hostile types, exception-raising attributes).
4. Defensive boundaries and resilience under manager persistence failures.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from unittest.mock import MagicMock, PropertyMock

import pytest

from src.core.config import ConfigData
from src.core.history_manager import SyncHistoryManager, SyncRunRecord
from src.core.sync_worker import SyncStatus, SyncWorker
from src.utils.log_handler import GuiLogHandler


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
            rec = worker._record_sync_history(st, dur, files, b_trans, err)
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
            rec = worker._record_sync_history("SUCCESS", 1.0, [f"f_{i}.md"])
            assert rec is not None
        assert len(hm) == 3

        # Phase 2: Clear history
        hm.clear_history()
        assert len(hm) == 0
        assert bool(hm) is True
        assert json.loads(hist_file.read_text(encoding="utf-8")) == []

        # Phase 3: Record immediately following clear
        rec_post_clear = worker._record_sync_history("SUCCESS", 2.0, ["after_clear.md"])
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

    def test_streaming_sync_records_history_when_initially_empty(self, tmp_path):
        """run_streaming_sync correctly records to initially empty SyncHistoryManager."""
        hist_file = tmp_path / "streaming_sync_history.json"
        hm = SyncHistoryManager(history_file=hist_file)
        assert len(hm) == 0

        worker = SyncWorker(config=MagicMock(), rclone_manager=MagicMock(), history_manager=hm)

        # Mock _stream_subprocess for SUCCESS
        worker._stream_subprocess = MagicMock(return_value=(0, "Transferred 1 files", ["doc.md"], 1024, set()))
        success, details = worker.run_streaming_sync(cmd=["dummy"])
        assert success is True
        assert len(hm) == 1
        assert hm.get_recent_runs()[0].status == "SUCCESS"
        assert hm.get_recent_runs()[0].bytes_transferred == 1024

        # Mock _stream_subprocess for CONFLICT
        worker._stream_subprocess = MagicMock(return_value=(0, "Conflict on c.md", ["c.md"], 512, {"c.md"}))
        success, details = worker.run_streaming_sync(cmd=["dummy"])
        assert success is True
        assert len(hm) == 2
        assert hm.get_recent_runs()[0].status == "CONFLICT"

        # Mock _stream_subprocess for FAILURE (non-zero return code)
        worker._stream_subprocess = MagicMock(return_value=(1, "Fatal error connecting", [], 0, set()))
        success, details = worker.run_streaming_sync(cmd=["dummy"])
        assert success is False
        assert len(hm) == 3
        assert hm.get_recent_runs()[0].status == "ERROR"

    def test_execute_sync_presync_validation_errors_recorded_when_initially_empty(self, tmp_path):
        """_execute_sync pre-sync validation failures record ERROR history when empty."""
        hist_file = tmp_path / "presync_err_history.json"
        hm = SyncHistoryManager(history_file=hist_file)
        assert len(hm) == 0

        # Subcase A: Missing local_vault_path
        cfg = MagicMock()
        cfg.local_vault_path = ""
        worker = SyncWorker(config=cfg, rclone_manager=MagicMock(), history_manager=hm)
        ok = worker._execute_sync()
        assert ok is False
        assert len(hm) == 1
        rec1 = hm.get_recent_runs()[0]
        assert rec1.status == "ERROR"
        assert "no configurada" in (rec1.error_message or "")

        # Subcase B: Non-existent vault directory
        cfg.local_vault_path = str(tmp_path / "nonexistent_dir_12345")
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


class TestConfigMockAndNoneEdgeCases:
    """Group 3: Tests config=None, MagicMock attributes, hostile types, and exceptions."""

    def test_config_is_none(self, tmp_path):
        """When worker.config is None, _record_sync_history defaults vault_name without failing."""
        hist_file = tmp_path / "config_none.json"
        hm = SyncHistoryManager(history_file=hist_file)

        worker = SyncWorker(config=None, rclone_manager=MagicMock(), history_manager=hm)
        rec = worker._record_sync_history("SUCCESS", 1.2, ["file.md"], 100)

        assert rec is not None
        assert rec.vault_name == "Principal"
        assert len(hm) == 1

        reloaded = SyncHistoryManager(history_file=hist_file)
        assert reloaded.get_recent_runs()[0].vault_name == "Principal"

    def test_config_is_raw_magicmock(self, tmp_path):
        """Raw MagicMock config must not leak child MagicMocks into vault_name."""
        hist_file = tmp_path / "config_raw_mock.json"
        hm = SyncHistoryManager(history_file=hist_file)

        mock_cfg = MagicMock()
        # In a raw MagicMock, mock_cfg.active_vault is a MagicMock, and active_vault.name is a MagicMock
        assert isinstance(mock_cfg.active_vault.name, MagicMock)

        worker = SyncWorker(config=mock_cfg, rclone_manager=MagicMock(), history_manager=hm)
        rec = worker._record_sync_history("SUCCESS", 1.0, ["file.md"])

        assert rec is not None
        assert isinstance(rec.vault_name, str)
        assert rec.vault_name == "Principal"
        assert len(hm) == 1

        # Verify disk JSON can be parsed cleanly
        raw = json.loads(hist_file.read_text(encoding="utf-8"))
        assert raw[0]["vault_name"] == "Principal"

    @pytest.mark.parametrize(
        "hostile_name",
        [
            12345,
            3.14159,
            None,
            [],
            {},
            object(),
            "",
            "   ",
            b"bytes_name",
        ],
    )
    def test_config_hostile_active_vault_name_types(self, hostile_name, tmp_path):
        """Non-string active_vault.name types safely fall back to 'Principal'."""
        hist_file = tmp_path / "hostile_types.json"
        hm = SyncHistoryManager(history_file=hist_file)

        mock_vault = MagicMock()
        mock_vault.name = hostile_name

        mock_cfg = MagicMock()
        mock_cfg.active_vault = mock_vault
        mock_cfg.get_active_vault = None

        worker = SyncWorker(config=mock_cfg, rclone_manager=MagicMock(), history_manager=hm)
        rec = worker._record_sync_history("SUCCESS", 1.0, ["test.md"])

        assert rec is not None
        assert rec.vault_name == "Principal"
        assert len(hm) == 1

    def test_config_whitespace_vault_name_stripped(self, tmp_path):
        """Valid string vault name with leading/trailing whitespace is cleanly stripped."""
        hist_file = tmp_path / "whitespace_vault.json"
        hm = SyncHistoryManager(history_file=hist_file)

        mock_vault = MagicMock()
        mock_vault.name = "  My Obsidian Notes   "

        mock_cfg = MagicMock()
        mock_cfg.active_vault = mock_vault

        worker = SyncWorker(config=mock_cfg, rclone_manager=MagicMock(), history_manager=hm)
        rec = worker._record_sync_history("SUCCESS", 1.0, ["test.md"])

        assert rec is not None
        assert rec.vault_name == "My Obsidian Notes"

    def test_config_fallback_to_callable_get_active_vault(self, tmp_path):
        """When active_vault is None or invalid, falls back to get_active_vault()."""
        hist_file = tmp_path / "fallback_get_active.json"
        hm = SyncHistoryManager(history_file=hist_file)

        mock_vault = MagicMock()
        mock_vault.name = "SecondaryVault"

        mock_cfg = MagicMock()
        mock_cfg.active_vault = None
        mock_cfg.get_active_vault.return_value = mock_vault

        worker = SyncWorker(config=mock_cfg, rclone_manager=MagicMock(), history_manager=hm)
        rec = worker._record_sync_history("SUCCESS", 1.0, ["test.md"])

        assert rec is not None
        assert rec.vault_name == "SecondaryVault"

    def test_config_attribute_access_raising_exceptions(self, tmp_path):
        """Exceptions raised during config inspection are caught and fall back to 'Principal'."""
        hist_file = tmp_path / "config_exception.json"
        hm = SyncHistoryManager(history_file=hist_file)

        # Subcase A: active_vault property raises RuntimeError
        class ExplodingConfig1:
            @property
            def active_vault(self):
                raise RuntimeError("Exploding active_vault property")

        worker1 = SyncWorker(config=ExplodingConfig1(), rclone_manager=MagicMock(), history_manager=hm)
        rec1 = worker1._record_sync_history("SUCCESS", 1.0, ["f1.md"])
        assert rec1 is not None
        assert rec1.vault_name == "Principal"

        # Subcase B: get_active_vault raises Exception
        class ExplodingConfig2:
            active_vault = None

            def get_active_vault(self):
                raise ValueError("Exploding get_active_vault method")

        worker2 = SyncWorker(config=ExplodingConfig2(), rclone_manager=MagicMock(), history_manager=hm)
        rec2 = worker2._record_sync_history("SUCCESS", 1.0, ["f2.md"])
        assert rec2 is not None
        assert rec2.vault_name == "Principal"

    @pytest.mark.parametrize("primitive_config", ["string_cfg", 999, [1, 2, 3], {"a": 1}])
    def test_config_primitive_types_handled_safely(self, primitive_config, tmp_path):
        """Primitive types passed as config fall back to 'Principal' cleanly."""
        hist_file = tmp_path / "primitive_cfg.json"
        hm = SyncHistoryManager(history_file=hist_file)

        worker = SyncWorker(config=primitive_config, rclone_manager=MagicMock(), history_manager=hm)
        rec = worker._record_sync_history("SUCCESS", 0.5, ["note.md"])

        assert rec is not None
        assert rec.vault_name == "Principal"

    def test_history_manager_is_none_returns_none(self):
        """When history_manager is None, _record_sync_history returns None safely."""
        worker = SyncWorker(config=MagicMock(), rclone_manager=MagicMock(), history_manager=None)
        res = worker._record_sync_history("SUCCESS", 1.0, ["f.md"])
        assert res is None


class TestDefensiveBoundariesAndResilience:
    """Group 4: Tests exception suppression and argument coercion."""

    def test_record_sync_history_catches_manager_exceptions(self):
        """Exceptions thrown inside history_manager.record_run are swallowed without disrupting worker."""
        broken_hm = MagicMock()
        broken_hm.record_run.side_effect = IOError("Disk full or permission denied")

        worker = SyncWorker(config=MagicMock(), rclone_manager=MagicMock(), history_manager=broken_hm)
        res = worker._record_sync_history("SUCCESS", 1.0, ["file.md"])

        assert res is None, "Expected None return when manager throws"
        broken_hm.record_run.assert_called_once()

    def test_record_sync_history_coerces_defensive_parameters(self, tmp_path):
        """Negative durations, case-folding of status, and collection coercion."""
        hist_file = tmp_path / "coercion_history.json"
        hm = SyncHistoryManager(history_file=hist_file)
        worker = SyncWorker(config=MagicMock(), rclone_manager=MagicMock(), history_manager=hm)

        # 1. Negative duration clamped to 0.0
        r1 = worker._record_sync_history("success", -5.5, ("file_a.md", "file_b.md"), 100)
        assert r1.status == "SUCCESS"
        assert r1.duration_seconds == 0.0
        assert r1.files_transferred == ["file_a.md", "file_b.md"]

        # 2. None files_transferred coerced to []
        r2 = worker._record_sync_history("error", 2.0, None)
        assert r2.status == "ERROR"
        assert r2.files_transferred == []

        # 3. Large duration and large byte count
        r3 = worker._record_sync_history("PARTIAL", 86400.123, ["huge.iso"], 10**11)
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
                    worker._record_sync_history("SUCCESS", 0.1, [f"rec_{idx}_{j}.md"])
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

    def test_dynamic_vault_switching_in_worker(self, tmp_path):
        """Worker properly preserves vault names when active vault changes dynamically."""
        hist_file = tmp_path / "dynamic_vaults.json"
        hm = SyncHistoryManager(history_file=hist_file)

        cfg = ConfigData(local_vault_path=str(tmp_path / "V1"))
        v2 = cfg.add_vault("SecondVault", str(tmp_path / "V2"))
        v3 = cfg.add_vault("ThirdVault", str(tmp_path / "V3"))

        worker = SyncWorker(config=cfg, rclone_manager=MagicMock(), history_manager=hm)

        # Default active vault is Principal
        r1 = worker._record_sync_history("SUCCESS", 1.0, ["v1.md"])
        assert r1.vault_name == "Principal"

        # Switch to SecondVault
        cfg.set_active_vault(v2.id)
        r2 = worker._record_sync_history("SUCCESS", 1.0, ["v2.md"])
        assert r2.vault_name == "SecondVault"

        # Switch to ThirdVault
        cfg.set_active_vault(v3.id)
        r3 = worker._record_sync_history("SUCCESS", 1.0, ["v3.md"])
        assert r3.vault_name == "ThirdVault"

        assert len(hm) == 3
        runs = hm.get_recent_runs()
        assert [r.vault_name for r in runs] == ["ThirdVault", "SecondVault", "Principal"]

    def test_falsy_config_instance_falls_back_cleanly(self, tmp_path):
        """A config object whose __bool__ evaluates to False safely falls back to 'Principal'."""
        hist_file = tmp_path / "falsy_config.json"
        hm = SyncHistoryManager(history_file=hist_file)

        class FalsyConfig:
            def __bool__(self):
                return False

            active_vault = MagicMock()

        worker = SyncWorker(config=FalsyConfig(), rclone_manager=MagicMock(), history_manager=hm)
        rec = worker._record_sync_history("SUCCESS", 1.0, ["falsy.md"])

        assert rec is not None
        assert rec.vault_name == "Principal"
        assert len(hm) == 1

