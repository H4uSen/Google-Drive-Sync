"""
Comprehensive Unit Test Suite for SyncHistoryManager and SyncRunRecord.
Tests ring buffer capacity, atomic persistence, corrupted JSON auto-recovery,
thread concurrency, and reverse-chronological ordering.
"""
import json
import os
import threading
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

from src.core.history_manager import SyncHistoryManager, SyncRunRecord
from src.core.sync_worker import SyncWorker
from src.core.config import VaultProfile
from src.utils.paths import get_history_file_path


class TestSyncRunRecordModel:
    def test_record_default_fields(self):
        rec = SyncRunRecord(
            id="sync_01",
            timestamp="2026-10-03T12:00:00Z",
            vault_name="MainVault",
            status="SUCCESS",
            duration_seconds=2.5,
        )
        assert rec.files_transferred == []
        assert rec.error_message is None
        assert rec.bytes_transferred == 0

    def test_record_custom_fields(self):
        rec = SyncRunRecord(
            id="sync_02",
            timestamp="2026-10-03T12:00:00Z",
            vault_name="WorkVault",
            status="ERROR",
            duration_seconds=5.1,
            files_transferred=["Notes/Todo.md", "Notes/Done.md"],
            error_message="Network unreachable",
            bytes_transferred=1024,
        )
        assert rec.id == "sync_02"
        assert rec.vault_name == "WorkVault"
        assert rec.status == "ERROR"
        assert rec.duration_seconds == 5.1
        assert len(rec.files_transferred) == 2
        assert rec.error_message == "Network unreachable"
        assert rec.bytes_transferred == 1024

    def test_record_serialization_roundtrip(self):
        rec = SyncRunRecord(
            id="sync_03",
            timestamp="2026-10-03T12:00:00Z",
            vault_name="MainVault",
            status="SUCCESS",
            duration_seconds=1.23,
            files_transferred=["a.md"],
            error_message=None,
            bytes_transferred=512,
        )
        d = rec.to_dict()
        assert isinstance(d, dict)
        restored = SyncRunRecord.from_dict(d)
        assert restored == rec

    def test_record_from_dict_defensive_parsing(self):
        raw = {
            "id": "sync_04",
            "timestamp": "2026-10-03T12:00:00Z",
            "vault_name": "MainVault",
            "status": "success",
            "duration_seconds": "3.5",
            "bytes_transferred": "2048",
            "files_transferred": ["x.md"],
            "extra_future_field": "ignore_me",
        }
        rec = SyncRunRecord.from_dict(raw)
        assert rec.status == "SUCCESS"
        assert rec.duration_seconds == 3.5
        assert rec.bytes_transferred == 2048
        assert rec.files_transferred == ["x.md"]


class TestSyncHistoryManagerInitialization:
    def test_init_default_path_uses_app_dir(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        mgr = SyncHistoryManager()
        assert mgr.history_file == get_history_file_path()

    def test_init_custom_path_pathlib_and_str(self, tmp_path):
        p1 = tmp_path / "custom1.json"
        mgr1 = SyncHistoryManager(history_file=p1)
        assert mgr1.history_file == p1

        p2 = str(tmp_path / "custom2.json")
        mgr2 = SyncHistoryManager(history_file=p2)
        assert mgr2.history_file == Path(p2)

    def test_init_empty_state_when_no_file_exists(self, tmp_path):
        mgr = SyncHistoryManager(history_file=tmp_path / "missing.json")
        assert mgr.get_recent_runs() == []
        assert len(mgr) == 0

    def test_bool_truthiness_when_empty_and_populated(self, tmp_path):
        mgr = SyncHistoryManager(history_file=tmp_path / "empty.json")
        assert len(mgr) == 0
        assert bool(mgr) is True

        rec = SyncRunRecord(
            id="run_bool",
            timestamp="2026-10-03T10:00:00Z",
            vault_name="MainVault",
            status="SUCCESS",
            duration_seconds=1.0,
        )
        mgr.record_run(rec)
        assert len(mgr) == 1
        assert bool(mgr) is True

        mgr.clear_history()
        assert len(mgr) == 0
        assert bool(mgr) is True

    def test_init_loads_existing_valid_file(self, tmp_path):
        target = tmp_path / "existing.json"
        data = [
            {
                "id": "run_01",
                "timestamp": "2026-10-03T10:00:00Z",
                "vault_name": "V1",
                "status": "SUCCESS",
                "duration_seconds": 1.0,
                "files_transferred": ["file.md"],
                "error_message": None,
                "bytes_transferred": 100,
            }
        ]
        target.write_text(json.dumps(data), encoding="utf-8")
        mgr = SyncHistoryManager(history_file=target)
        runs = mgr.get_recent_runs()
        assert len(runs) == 1
        assert runs[0].id == "run_01"


class TestSyncHistoryManagerRecordRun:
    def test_record_single_run_in_memory_and_disk(self, tmp_path):
        f = tmp_path / "hist.json"
        mgr = SyncHistoryManager(history_file=f)
        rec = SyncRunRecord(
            id="run_1",
            timestamp="2026-10-03T12:00:00Z",
            vault_name="V",
            status="SUCCESS",
            duration_seconds=1.5,
        )
        mgr.record_run(rec)
        assert len(mgr) == 1
        assert f.exists()
        raw = json.loads(f.read_text(encoding="utf-8"))
        assert len(raw) == 1
        assert raw[0]["id"] == "run_1"

    def test_record_multiple_runs_preserves_order(self, tmp_path):
        mgr = SyncHistoryManager(history_file=tmp_path / "hist.json")
        for i in range(3):
            mgr.record_run(
                SyncRunRecord(
                    id=f"run_{i}",
                    timestamp=f"2026-10-03T12:0{i}:00Z",
                    vault_name="V",
                    status="SUCCESS",
                    duration_seconds=1.0,
                )
            )
        runs = mgr.get_recent_runs()
        assert [r.id for r in runs] == ["run_2", "run_1", "run_0"]

    def test_record_run_all_status_types(self, tmp_path):
        mgr = SyncHistoryManager(history_file=tmp_path / "hist.json")
        statuses = ["SUCCESS", "ERROR", "CONFLICT", "PARTIAL"]
        for s in statuses:
            mgr.record_run(
                SyncRunRecord(
                    id=f"run_{s}",
                    timestamp="2026-10-03T12:00:00Z",
                    vault_name="V",
                    status=s,
                    duration_seconds=1.0,
                )
            )
        recorded = [r.status for r in mgr.get_recent_runs()]
        assert recorded == ["PARTIAL", "CONFLICT", "ERROR", "SUCCESS"]

    def test_record_run_with_large_file_list(self, tmp_path):
        mgr = SyncHistoryManager(history_file=tmp_path / "hist.json")
        large_files = [f"Notes/Doc_{i}.md" for i in range(500)]
        mgr.record_run(
            SyncRunRecord(
                id="run_large",
                timestamp="2026-10-03T12:00:00Z",
                vault_name="V",
                status="SUCCESS",
                duration_seconds=10.0,
                files_transferred=large_files,
            )
        )
        runs = mgr.get_recent_runs()
        assert len(runs[0].files_transferred) == 500

    def test_record_run_invalid_type_raises(self, tmp_path):
        mgr = SyncHistoryManager(history_file=tmp_path / "hist.json")
        with pytest.raises(TypeError):
            mgr.record_run({"not": "a SyncRunRecord"})


class TestSyncHistoryManagerRingBuffer:
    def test_ring_buffer_exact_capacity_100(self, tmp_path):
        mgr = SyncHistoryManager(history_file=tmp_path / "hist.json", max_records=100)
        for i in range(100):
            mgr.record_run(
                SyncRunRecord(
                    id=f"run_{i}",
                    timestamp="2026-10-03T12:00:00Z",
                    vault_name="V",
                    status="SUCCESS",
                    duration_seconds=1.0,
                )
            )
        assert len(mgr) == 100
        assert len(mgr.get_recent_runs(200)) == 100

    def test_ring_buffer_evicts_oldest_on_101st_record(self, tmp_path):
        mgr = SyncHistoryManager(history_file=tmp_path / "hist.json", max_records=100)
        for i in range(101):
            mgr.record_run(
                SyncRunRecord(
                    id=f"run_{i}",
                    timestamp="2026-10-03T12:00:00Z",
                    vault_name="V",
                    status="SUCCESS",
                    duration_seconds=1.0,
                )
            )
        all_runs = mgr.get_recent_runs(200)
        assert len(all_runs) == 100
        ids = [r.id for r in all_runs]
        assert "run_0" not in ids
        assert ids[0] == "run_100"
        assert ids[-1] == "run_1"

    def test_ring_buffer_large_overflow_250_records(self, tmp_path):
        mgr = SyncHistoryManager(history_file=tmp_path / "hist.json", max_records=100)
        for i in range(250):
            mgr.record_run(
                SyncRunRecord(
                    id=f"run_{i}",
                    timestamp="2026-10-03T12:00:00Z",
                    vault_name="V",
                    status="SUCCESS",
                    duration_seconds=1.0,
                )
            )
        assert len(mgr) == 100
        assert mgr.get_recent_runs()[0].id == "run_249"

    def test_ring_buffer_custom_max_records(self, tmp_path):
        mgr = SyncHistoryManager(history_file=tmp_path / "hist.json", max_records=5)
        for i in range(10):
            mgr.record_run(
                SyncRunRecord(
                    id=f"run_{i}",
                    timestamp="2026-10-03T12:00:00Z",
                    vault_name="V",
                    status="SUCCESS",
                    duration_seconds=1.0,
                )
            )
        assert len(mgr) == 5
        assert [r.id for r in mgr.get_recent_runs()] == ["run_9", "run_8", "run_7", "run_6", "run_5"]

    def test_ring_buffer_persisted_state_respects_cap(self, tmp_path):
        f = tmp_path / "hist.json"
        mgr = SyncHistoryManager(history_file=f, max_records=100)
        for i in range(120):
            mgr.record_run(
                SyncRunRecord(
                    id=f"run_{i}",
                    timestamp="2026-10-03T12:00:00Z",
                    vault_name="V",
                    status="SUCCESS",
                    duration_seconds=1.0,
                )
            )
        data = json.loads(f.read_text(encoding="utf-8"))
        assert len(data) == 100


class TestSyncHistoryManagerQueriesAndOrdering:
    def test_get_recent_runs_newest_first(self, tmp_path):
        mgr = SyncHistoryManager(history_file=tmp_path / "hist.json")
        for i in range(5):
            mgr.record_run(
                SyncRunRecord(
                    id=f"id_{i}",
                    timestamp="2026-10-03T12:00:00Z",
                    vault_name="V",
                    status="SUCCESS",
                    duration_seconds=1.0,
                )
            )
        runs = mgr.get_recent_runs()
        assert runs[0].id == "id_4"

    def test_get_recent_runs_default_limit_20(self, tmp_path):
        mgr = SyncHistoryManager(history_file=tmp_path / "hist.json")
        for i in range(35):
            mgr.record_run(
                SyncRunRecord(
                    id=f"id_{i}",
                    timestamp="2026-10-03T12:00:00Z",
                    vault_name="V",
                    status="SUCCESS",
                    duration_seconds=1.0,
                )
            )
        assert len(mgr.get_recent_runs()) == 20

    def test_get_recent_runs_custom_limit(self, tmp_path):
        mgr = SyncHistoryManager(history_file=tmp_path / "hist.json")
        for i in range(10):
            mgr.record_run(
                SyncRunRecord(
                    id=f"id_{i}",
                    timestamp="2026-10-03T12:00:00Z",
                    vault_name="V",
                    status="SUCCESS",
                    duration_seconds=1.0,
                )
            )
        assert len(mgr.get_recent_runs(limit=4)) == 4

    def test_get_recent_runs_limit_exceeds_total(self, tmp_path):
        mgr = SyncHistoryManager(history_file=tmp_path / "hist.json")
        mgr.record_run(
            SyncRunRecord(
                id="id_0",
                timestamp="2026-10-03T12:00:00Z",
                vault_name="V",
                status="SUCCESS",
                duration_seconds=1.0,
            )
        )
        assert len(mgr.get_recent_runs(limit=100)) == 1

    def test_get_recent_runs_zero_or_negative_limit(self, tmp_path):
        mgr = SyncHistoryManager(history_file=tmp_path / "hist.json")
        mgr.record_run(
            SyncRunRecord(
                id="id_0",
                timestamp="2026-10-03T12:00:00Z",
                vault_name="V",
                status="SUCCESS",
                duration_seconds=1.0,
            )
        )
        assert mgr.get_recent_runs(limit=0) == []
        assert mgr.get_recent_runs(limit=-5) == []

    def test_get_run_by_id(self, tmp_path):
        mgr = SyncHistoryManager(history_file=tmp_path / "hist.json")
        rec = SyncRunRecord(
            id="target_run",
            timestamp="2026-10-03T12:00:00Z",
            vault_name="V",
            status="SUCCESS",
            duration_seconds=1.0,
        )
        mgr.record_run(rec)
        assert mgr.get_run_by_id("target_run") == rec
        assert mgr.get_run_by_id("nonexistent") is None

    def test_len_magic_method(self, tmp_path):
        mgr = SyncHistoryManager(history_file=tmp_path / "hist.json")
        assert len(mgr) == 0
        mgr.record_run(
            SyncRunRecord(
                id="r1",
                timestamp="2026-10-03T12:00:00Z",
                vault_name="V",
                status="SUCCESS",
                duration_seconds=1.0,
            )
        )
        assert len(mgr) == 1


class TestSyncHistoryManagerClear:
    def test_clear_history_empties_memory_and_disk(self, tmp_path):
        f = tmp_path / "hist.json"
        mgr = SyncHistoryManager(history_file=f)
        mgr.record_run(
            SyncRunRecord(
                id="r1",
                timestamp="2026-10-03T12:00:00Z",
                vault_name="V",
                status="SUCCESS",
                duration_seconds=1.0,
            )
        )
        assert len(mgr) == 1
        mgr.clear_history()
        assert len(mgr) == 0
        assert mgr.get_recent_runs() == []
        data = json.loads(f.read_text(encoding="utf-8"))
        assert data == []

    def test_clear_history_reloaded_instance_remains_empty(self, tmp_path):
        f = tmp_path / "hist.json"
        mgr = SyncHistoryManager(history_file=f)
        mgr.record_run(
            SyncRunRecord(
                id="r1",
                timestamp="2026-10-03T12:00:00Z",
                vault_name="V",
                status="SUCCESS",
                duration_seconds=1.0,
            )
        )
        mgr.clear_history()
        mgr2 = SyncHistoryManager(history_file=f)
        assert len(mgr2) == 0

    def test_record_run_after_clear_starts_fresh(self, tmp_path):
        mgr = SyncHistoryManager(history_file=tmp_path / "hist.json")
        mgr.record_run(
            SyncRunRecord(
                id="r1",
                timestamp="2026-10-03T12:00:00Z",
                vault_name="V",
                status="SUCCESS",
                duration_seconds=1.0,
            )
        )
        mgr.clear_history()
        mgr.record_run(
            SyncRunRecord(
                id="r2",
                timestamp="2026-10-03T12:00:00Z",
                vault_name="V",
                status="SUCCESS",
                duration_seconds=1.0,
            )
        )
        assert len(mgr) == 1
        assert mgr.get_recent_runs()[0].id == "r2"


class TestSyncHistoryManagerAtomicPersistence:
    def test_persistence_disk_file_is_valid_json(self, tmp_path):
        f = tmp_path / "hist.json"
        mgr = SyncHistoryManager(history_file=f)
        mgr.record_run(
            SyncRunRecord(
                id="r1",
                timestamp="2026-10-03T12:00:00Z",
                vault_name="V",
                status="SUCCESS",
                duration_seconds=1.0,
            )
        )
        parsed = json.loads(f.read_text(encoding="utf-8"))
        assert isinstance(parsed, list)
        assert parsed[0]["id"] == "r1"

    def test_persistence_parent_directory_creation(self, tmp_path):
        nested = tmp_path / "deep" / "nested" / "dir" / "hist.json"
        mgr = SyncHistoryManager(history_file=nested)
        mgr.record_run(
            SyncRunRecord(
                id="r1",
                timestamp="2026-10-03T12:00:00Z",
                vault_name="V",
                status="SUCCESS",
                duration_seconds=1.0,
            )
        )
        assert nested.exists()

    def test_atomic_save_cleans_up_temp_on_failure(self, tmp_path):
        f = tmp_path / "hist.json"
        mgr = SyncHistoryManager(history_file=f)
        with patch("json.dump", side_effect=IOError("Simulated write error")):
            with pytest.raises(IOError):
                mgr.record_run(
                    SyncRunRecord(
                        id="r1",
                        timestamp="2026-10-03T12:00:00Z",
                        vault_name="V",
                        status="SUCCESS",
                        duration_seconds=1.0,
                    )
                )
        # Ensure no orphan temp files remain in directory
        tmp_files = list(tmp_path.glob(".*.tmp"))
        assert len(tmp_files) == 0


class TestSyncHistoryManagerCorruptionRecovery:
    def test_corrupt_invalid_syntax(self, tmp_path):
        f = tmp_path / "hist.json"
        f.write_text("{ INVALID SYNTAX @@@ }}}", encoding="utf-8")
        mgr = SyncHistoryManager(history_file=f)
        assert mgr.get_recent_runs() == []
        assert (tmp_path / "hist.json.bak").exists()

    def test_corrupt_empty_file(self, tmp_path):
        f = tmp_path / "hist.json"
        f.write_text("", encoding="utf-8")
        mgr = SyncHistoryManager(history_file=f)
        assert mgr.get_recent_runs() == []

    def test_corrupt_whitespace_only(self, tmp_path):
        f = tmp_path / "hist.json"
        f.write_text("   \n\t  ", encoding="utf-8")
        mgr = SyncHistoryManager(history_file=f)
        assert mgr.get_recent_runs() == []

    def test_corrupt_non_list_root_object(self, tmp_path):
        f = tmp_path / "hist.json"
        f.write_text('{"records": []}', encoding="utf-8")
        mgr = SyncHistoryManager(history_file=f)
        assert mgr.get_recent_runs() == []
        assert (tmp_path / "hist.json.bak").exists()

    def test_corrupt_partial_elements_in_list(self, tmp_path):
        f = tmp_path / "hist.json"
        payload = [
            {
                "id": "valid_01",
                "timestamp": "2026-10-03T12:00:00Z",
                "vault_name": "V",
                "status": "SUCCESS",
                "duration_seconds": 1.0,
            },
            "broken string element",
            {"missing_fields": True},
        ]
        f.write_text(json.dumps(payload), encoding="utf-8")
        mgr = SyncHistoryManager(history_file=f)
        runs = mgr.get_recent_runs()
        # Salvages valid entries
        assert len(runs) >= 1
        assert runs[0].id == "valid_01"

    def test_corrupt_file_recovery_allows_subsequent_saves(self, tmp_path):
        f = tmp_path / "hist.json"
        f.write_text("Corrupted!", encoding="utf-8")
        mgr = SyncHistoryManager(history_file=f)
        assert mgr.get_recent_runs() == []
        mgr.record_run(
            SyncRunRecord(
                id="new_run",
                timestamp="2026-10-03T12:00:00Z",
                vault_name="V",
                status="SUCCESS",
                duration_seconds=1.0,
            )
        )
        assert len(mgr) == 1
        data = json.loads(f.read_text(encoding="utf-8"))
        assert len(data) == 1
        assert data[0]["id"] == "new_run"


class TestSyncHistoryManagerConcurrency:
    def test_concurrent_record_run_10_threads(self, tmp_path):
        mgr = SyncHistoryManager(history_file=tmp_path / "hist.json", max_records=100)
        barrier = threading.Barrier(10)
        errors = []

        def worker(tid: int):
            try:
                barrier.wait()
                for i in range(15):
                    mgr.record_run(
                        SyncRunRecord(
                            id=f"t{tid}_{i}",
                            timestamp="2026-10-03T12:00:00Z",
                            vault_name="V",
                            status="SUCCESS",
                            duration_seconds=1.0,
                        )
                    )
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        assert len(mgr) == 100

    def test_concurrent_readers_and_writers(self, tmp_path):
        mgr = SyncHistoryManager(history_file=tmp_path / "hist.json", max_records=50)
        stop = threading.Event()
        errors = []

        def writer():
            cnt = 0
            while not stop.is_set():
                try:
                    mgr.record_run(
                        SyncRunRecord(
                            id=f"w_{cnt}",
                            timestamp="2026-10-03T12:00:00Z",
                            vault_name="V",
                            status="SUCCESS",
                            duration_seconds=1.0,
                        )
                    )
                    cnt += 1
                except Exception as e:
                    errors.append(e)

        def reader():
            while not stop.is_set():
                try:
                    runs = mgr.get_recent_runs()
                    assert isinstance(runs, list)
                except Exception as e:
                    errors.append(e)

        w_thread = threading.Thread(target=writer)
        r_thread = threading.Thread(target=reader)
        w_thread.start()
        r_thread.start()

        import time
        time.sleep(0.1)
        stop.set()
        w_thread.join()
        r_thread.join()

        assert errors == []

    def test_concurrent_clear_and_record(self, tmp_path):
        mgr = SyncHistoryManager(history_file=tmp_path / "hist.json", max_records=50)
        stop = threading.Event()
        errors = []

        def worker_record():
            i = 0
            while not stop.is_set() and i < 50:
                try:
                    mgr.record_run(
                        SyncRunRecord(
                            id=f"r_{i}",
                            timestamp="2026-10-03T12:00:00Z",
                            vault_name="V",
                            status="SUCCESS",
                            duration_seconds=1.0,
                        )
                    )
                    i += 1
                except Exception as e:
                    errors.append(e)

        def worker_clear():
            while not stop.is_set():
                try:
                    mgr.clear_history()
                except Exception as e:
                    errors.append(e)

        t1 = threading.Thread(target=worker_record)
        t2 = threading.Thread(target=worker_clear)
        t1.start()
        t2.start()

        import time
        time.sleep(0.05)
        stop.set()
        t1.join()
        t2.join()

        assert errors == []


class TestSyncHistoryManagerEdgeCases:
    def test_special_characters_and_emojis(self, tmp_path):
        mgr = SyncHistoryManager(history_file=tmp_path / "hist.json")
        rec = SyncRunRecord(
            id="sync_unicode_⚡",
            timestamp="2026-10-03T12:00:00Z",
            vault_name="Vault 📚 日本語 🚀",
            status="SUCCESS",
            duration_seconds=1.23,
            files_transferred=["Notes/Español.md", "Notes/日本語/メモ.md", "Folder with spaces & (symbols)/file.txt"],
            error_message="No error 🎉",
            bytes_transferred=9999,
        )
        mgr.record_run(rec)
        reloaded = SyncHistoryManager(history_file=tmp_path / "hist.json")
        read_rec = reloaded.get_recent_runs()[0]
        assert read_rec.id == "sync_unicode_⚡"
        assert read_rec.vault_name == "Vault 📚 日本語 🚀"
        assert read_rec.files_transferred == rec.files_transferred
        assert read_rec.error_message == "No error 🎉"


VAULT = VaultProfile(name="Principal")


class TestSyncWorkerHistoryIntegration:
    """Integration tests verifying SyncWorker interaction with SyncHistoryManager."""

    def test_record_sync_history_with_initially_empty_manager(self, tmp_path):
        """Worker must record history when history manager starts with 0 records."""
        hist_file = tmp_path / "sync_history.json"
        hm = SyncHistoryManager(history_file=hist_file)
        assert len(hm) == 0
        assert bool(hm) is True

        worker = SyncWorker(config=MagicMock(), rclone_manager=MagicMock(), history_manager=hm)
        rec = worker._record_sync_history(
            VAULT,
            status="SUCCESS",
            duration=1.45,
            files_transferred=["Daily/2026-10-03.md"],
            bytes_transferred=2048,
        )

        assert rec is not None
        assert len(hm) == 1
        assert hist_file.exists()

        stored = hm.get_recent_runs()[0]
        assert stored.status == "SUCCESS"
        assert stored.duration_seconds == 1.45
        assert stored.files_transferred == ["Daily/2026-10-03.md"]
        assert stored.bytes_transferred == 2048

    def test_record_sync_history_multiple_statuses(self, tmp_path):
        """Worker records SUCCESS, ERROR, CONFLICT, and PARTIAL statuses correctly."""
        hist_file = tmp_path / "sync_history.json"
        hm = SyncHistoryManager(history_file=hist_file)

        worker = SyncWorker(config=MagicMock(), rclone_manager=MagicMock(), history_manager=hm)

        r1 = worker._record_sync_history(VAULT, "SUCCESS", 1.2, ["note1.md"], 512)
        r2 = worker._record_sync_history(VAULT, "ERROR", 0.5, [], error_message="Network error")
        r3 = worker._record_sync_history(VAULT, "CONFLICT", 2.1, ["conflict.md"], 1024)
        r4 = worker._record_sync_history(VAULT, "PARTIAL", 3.0, ["p1.md", "p2.md"], 2048)

        assert r1 is not None and r2 is not None and r3 is not None and r4 is not None
        assert len(hm) == 4

        recent = hm.get_recent_runs(limit=10)
        assert [r.status for r in recent] == ["PARTIAL", "CONFLICT", "ERROR", "SUCCESS"]
        assert recent[2].error_message == "Network error"

    def test_record_sync_history_when_history_manager_is_none(self):
        """When history_manager is None, _record_sync_history safely returns None."""
        worker = SyncWorker(config=MagicMock(), rclone_manager=MagicMock(), history_manager=None)
        res = worker._record_sync_history(VAULT, "SUCCESS", 1.0, ["file.md"])
        assert res is None

    def test_record_sync_history_keeps_the_vault_name(self, tmp_path):
        """The name of the Vault passed in is stored, stripped, and survives a reload."""
        hist_file = tmp_path / "vault_name_history.json"
        hm = SyncHistoryManager(history_file=hist_file)

        worker = SyncWorker(config=MagicMock(), rclone_manager=MagicMock(), history_manager=hm)
        rec = worker._record_sync_history(VaultProfile(name="  ResearchNotes "), "SUCCESS", 2.0, ["paper.md"])

        assert rec.vault_name == "ResearchNotes"
        reloaded = SyncHistoryManager(history_file=hist_file)
        assert reloaded.get_recent_runs()[0].vault_name == "ResearchNotes"

    def test_record_sync_history_empty_or_none_files(self, tmp_path):
        """Worker cleanly records empty or None files_transferred without error."""
        hist_file = tmp_path / "empty_files_history.json"
        hm = SyncHistoryManager(history_file=hist_file)

        worker = SyncWorker(config=MagicMock(), rclone_manager=MagicMock(), history_manager=hm)
        rec = worker._record_sync_history(VAULT, "SUCCESS", 0.5, None)

        assert rec is not None
        assert rec.files_transferred == []
        assert len(hm) == 1
