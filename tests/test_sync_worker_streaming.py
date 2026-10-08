"""
Unit and integration tests for SyncWorker streaming execution, real-time line parsing,
event dispatching, timeout watchdog, cancellation, and error boundaries.
"""
import io
import time
import json
import pytest
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.core.sync_worker import SyncWorker, SyncStatus, parse_byte_size
from src.core.config import ConfigData
from src.core.events import (
    EventDispatcher,
    EventType,
    Event,
    FilePayload,
    ProgressPayload,
    ConflictPayload,
    BatchPayload,
    StatusPayload,
)


class MockStreamingPopen:
    """Simulates a streaming subprocess.Popen instance for unit testing."""
    def __init__(self, stdout_lines: list[str], returncode: int = 0, delay_per_line: float = 0.0):
        self.stdout_lines = list(stdout_lines)
        self.returncode = returncode
        self.delay_per_line = delay_per_line
        self.pid = 98765
        self.terminated = False
        self.killed = False
        self._wait_called = False
        self._lines_remaining = list(self.stdout_lines)

        class StdoutStream:
            def __init__(stream_self):
                pass

            def readline(stream_self):
                if self.delay_per_line > 0:
                    time.sleep(self.delay_per_line)
                if self._lines_remaining:
                    line = self._lines_remaining.pop(0)
                    return line if line.endswith("\n") else line + "\n"
                return ""

            def close(stream_self):
                pass

        self.stdout = StdoutStream()

    def poll(self):
        if self.terminated or self.killed:
            return self.returncode or -15
        if not self._lines_remaining:
            return self.returncode
        return None

    def wait(self, timeout=None):
        self._wait_called = True
        return self.returncode

    def terminate(self):
        self.terminated = True
        self._lines_remaining.clear()

    def kill(self):
        self.killed = True
        self._lines_remaining.clear()


class TestStreamingOutputParsing:
    def test_parse_byte_size_helper(self):
        assert parse_byte_size("22 B") == 22
        assert parse_byte_size("500 KiB") == 512000
        assert parse_byte_size("1 MiB") == 1048576
        assert parse_byte_size("2.5 MB") == 2500000
        assert parse_byte_size("1 GiB") == 1024**3
        assert parse_byte_size("invalid") == 0

    def test_streaming_file_transfers_emitted(self, tmp_path):
        vault = tmp_path / "vault"
        vault.mkdir()
        (vault / "note1.md").write_text("Hello 1", encoding="utf-8")
        (vault / "note2.md").write_text("Hello 2", encoding="utf-8")

        cfg = ConfigData(local_vault_path=str(vault), remote_folder_name="vault", first_sync_done=True)
        dispatcher = EventDispatcher()
        worker = SyncWorker(config=cfg, rclone_manager=MagicMock(), event_dispatcher=dispatcher)

        file_events: list[FilePayload] = []
        dispatcher.subscribe(EventType.FILE_TRANSFERRED, lambda ev: file_events.append(ev.data))

        sample_lines = [
            "2026/10/02 21:42:56 INFO  : note1.md: Copied (new)",
            "2026/10/02 21:42:56 INFO  : note2.md: Copied (replaced)",
            "2026/10/02 21:43:57 INFO  : old.md: Deleted",
            "2026/10/02 21:43:23 INFO  : moved.md: Moved (server-side) to: moved_remote.md",
        ]
        mock_proc = MockStreamingPopen(sample_lines, returncode=0)

        with patch("subprocess.Popen", return_value=mock_proc):
            success = worker._execute_sync()

        assert success is True
        assert len(file_events) == 4
        assert file_events[0].filename == "note1.md"
        assert file_events[0].action == "Copied (new)"
        assert file_events[0].size > 0

        assert file_events[1].filename == "note2.md"
        assert file_events[1].action == "Copied (replaced)"

        assert file_events[2].filename == "old.md"
        assert file_events[2].action == "Deleted"

        assert file_events[3].filename == "moved.md"

    def test_streaming_star_file_transfers(self, tmp_path):
        vault = tmp_path / "vault"
        vault.mkdir()
        cfg = ConfigData(local_vault_path=str(vault), remote_folder_name="vault", first_sync_done=True)
        dispatcher = EventDispatcher()
        worker = SyncWorker(config=cfg, rclone_manager=MagicMock(), event_dispatcher=dispatcher)

        file_events = []
        prog_events = []
        dispatcher.subscribe(EventType.FILE_TRANSFERRED, lambda ev: file_events.append(ev.data))
        dispatcher.subscribe(EventType.PROGRESS_UPDATED, lambda ev: prog_events.append(ev.data))

        sample_lines = [
            "* Notes/Project.md: 100% /100%, 50 KiB/s",
        ]
        mock_proc = MockStreamingPopen(sample_lines, returncode=0)

        with patch("subprocess.Popen", return_value=mock_proc):
            success = worker._execute_sync()

        assert success is True
        assert len(file_events) == 1
        assert file_events[0].filename == "Notes/Project.md"
        assert len(prog_events) == 1
        assert prog_events[0].current_file == "Notes/Project.md"
        assert prog_events[0].percentage == 100.0

    def test_streaming_progress_updates(self, tmp_path):
        vault = tmp_path / "vault"
        vault.mkdir()
        cfg = ConfigData(local_vault_path=str(vault), remote_folder_name="vault", first_sync_done=True)
        dispatcher = EventDispatcher()
        worker = SyncWorker(config=cfg, rclone_manager=MagicMock(), event_dispatcher=dispatcher)

        progress_events: list[ProgressPayload] = []
        dispatcher.subscribe(EventType.PROGRESS_UPDATED, lambda ev: progress_events.append(ev.data))

        sample_lines = [
            "Transferred:   	        2.450 MiB / 10.000 MiB, 24%, 1.2 MiB/s, ETA 6s",
            "Transferred: 500 KiB / 1 MiB, 50%, 100 KiB/s",
        ]
        mock_proc = MockStreamingPopen(sample_lines, returncode=0)

        with patch("subprocess.Popen", return_value=mock_proc):
            success = worker._execute_sync()

        assert success is True
        assert len(progress_events) == 2
        assert progress_events[0].percentage == 24.0
        assert progress_events[0].speed_str == "1.2 MiB/s"
        assert progress_events[0].eta_str == "6s"
        assert progress_events[1].percentage == 50.0

    def test_streaming_conflict_detection_and_deduplication(self, tmp_path):
        vault = tmp_path / "vault"
        vault.mkdir()
        cfg = ConfigData(local_vault_path=str(vault), remote_folder_name="vault", first_sync_done=True)
        dispatcher = EventDispatcher()
        worker = SyncWorker(config=cfg, rclone_manager=MagicMock(), event_dispatcher=dispatcher)

        conflict_events: list[ConflictPayload] = []
        dispatcher.subscribe(EventType.CONFLICT_DETECTED, lambda ev: conflict_events.append(ev.data))

        sample_lines = [
            "2026/10/02 21:43:23 NOTICE: - WARNING           New or changed in both paths                - note0.md",
            "2026/10/02 21:43:23 ERROR : note0.md: md5 differ",
            "2026/10/02 21:43:24 NOTICE: - WARNING           New or changed in both paths                - note0.md",
        ]
        mock_proc = MockStreamingPopen(sample_lines, returncode=0)

        with patch("subprocess.Popen", return_value=mock_proc):
            success = worker._execute_sync()

        assert success is True
        # note0.md should only trigger 1 conflict event due to deduplication set
        assert len(conflict_events) == 1
        assert conflict_events[0].filename == "note0.md"

    def test_streaming_batch_completion_event(self, tmp_path):
        vault = tmp_path / "vault"
        vault.mkdir()
        (vault / "f1.txt").write_text("data1", encoding="utf-8")
        (vault / "f2.txt").write_text("data2", encoding="utf-8")

        cfg = ConfigData(local_vault_path=str(vault), remote_folder_name="vault", first_sync_done=True)
        dispatcher = EventDispatcher()
        worker = SyncWorker(config=cfg, rclone_manager=MagicMock(), event_dispatcher=dispatcher)

        batch_events: list[BatchPayload] = []
        dispatcher.subscribe(EventType.BATCH_COMPLETED, lambda ev: batch_events.append(ev.data))

        sample_lines = [
            "2026/10/02 21:42:56 INFO  : f1.txt: Copied (new)",
            "2026/10/02 21:42:57 INFO  : f2.txt: Copied (new)",
        ]
        mock_proc = MockStreamingPopen(sample_lines, returncode=0)

        with patch("subprocess.Popen", return_value=mock_proc):
            success = worker._execute_sync()

        assert success is True
        assert len(batch_events) == 1
        assert batch_events[0].total_files == 2
        assert batch_events[0].status == "SUCCESS"
        assert batch_events[0].elapsed_seconds >= 0

    def test_streaming_log_emission(self, tmp_path):
        vault = tmp_path / "vault"
        vault.mkdir()
        cfg = ConfigData(local_vault_path=str(vault), remote_folder_name="vault", first_sync_done=True)
        dispatcher = EventDispatcher()
        worker = SyncWorker(config=cfg, rclone_manager=MagicMock(), event_dispatcher=dispatcher)

        log_events = []
        dispatcher.subscribe(EventType.LOG_EMITTED, lambda ev: log_events.append(ev.data))

        sample_lines = [
            "Normal informational log line",
            "ERROR : Some rclone failure",
        ]
        mock_proc = MockStreamingPopen(sample_lines, returncode=0)

        with patch("subprocess.Popen", return_value=mock_proc):
            worker._execute_sync()

        assert len(log_events) >= 2
        assert log_events[0].level == "INFO"
        assert log_events[1].level == "ERROR"


class TestStreamingLifecycleAndControl:
    def test_streaming_timeout_watchdog_terminates_process(self, tmp_path):
        vault = tmp_path / "vault"
        vault.mkdir()
        cfg = ConfigData(local_vault_path=str(vault), remote_folder_name="vault", first_sync_done=True)
        worker = SyncWorker(config=cfg, rclone_manager=MagicMock())

        # Simulate slow process that takes 0.5s per line
        mock_proc = MockStreamingPopen(["Line 1", "Line 2", "Line 3"], returncode=0, delay_per_line=0.5)

        with patch("subprocess.Popen", return_value=mock_proc), \
             patch.object(worker, "_stream_subprocess", side_effect=subprocess.TimeoutExpired(cmd=["rclone"], timeout=1)):
            success = worker._execute_sync()

        assert success is False
        assert worker.status == SyncStatus.ERROR
        assert "tiempo" in worker.last_message.lower() or "timeout" in worker.last_message.lower()

    def test_cancel_sync_terminates_active_process(self, tmp_path):
        vault = tmp_path / "vault"
        vault.mkdir()
        cfg = ConfigData(local_vault_path=str(vault), remote_folder_name="vault", first_sync_done=True)
        worker = SyncWorker(config=cfg, rclone_manager=MagicMock())

        mock_proc = MockStreamingPopen(["Line 1\n", "Line 2\n"], returncode=0)
        worker._process = mock_proc

        worker.cancel_sync()
        assert worker._cancelled is True
        assert mock_proc.terminated is True

    def test_stop_worker_triggers_cancellation(self, tmp_path):
        vault = tmp_path / "vault"
        vault.mkdir()
        cfg = ConfigData(local_vault_path=str(vault), remote_folder_name="vault", first_sync_done=True)
        worker = SyncWorker(config=cfg, rclone_manager=MagicMock())

        mock_proc = MockStreamingPopen(["Line 1"], returncode=0)
        worker._process = mock_proc

        worker.stop()
        assert worker._running is False
        assert mock_proc.terminated is True

    def test_run_streaming_sync_programmatic_interface(self, tmp_path):
        vault = tmp_path / "vault"
        vault.mkdir()
        cfg = ConfigData(local_vault_path=str(vault), remote_folder_name="vault", first_sync_done=True)
        mock_rclone = MagicMock()
        mock_rclone.build_bisync_command.return_value = ["mock_rclone"]
        worker = SyncWorker(config=cfg, rclone_manager=mock_rclone)

        sample_lines = [
            "Transferred: 1 MiB / 2 MiB, 50%, 1 MiB/s",
            "2026/10/02 21:42:56 INFO  : f1.md: Copied (new)",
        ]
        mock_proc = MockStreamingPopen(sample_lines, returncode=0)

        with patch("subprocess.Popen", return_value=mock_proc):
            success, details = worker.run_streaming_sync()

        assert success is True
        assert isinstance(details, dict)
        assert details["files"] == ["f1.md"]
        assert details["returncode"] == 0
        assert "elapsed_seconds" in details


class TestStreamingErrorBoundaries:
    def test_streaming_safety_abort_forbids_auto_resync(self, tmp_path):
        vault = tmp_path / "vault"
        vault.mkdir()
        cfg = ConfigData(local_vault_path=str(vault), remote_folder_name="vault", first_sync_done=True)
        mock_rclone = MagicMock()
        mock_rclone.build_bisync_command.return_value = ["mock_rclone"]
        worker = SyncWorker(config=cfg, rclone_manager=mock_rclone)

        error_lines = [
            "ERROR : Safety abort: all files were changed on Path1. Run with --force if desired.",
            "Fatal error: Must run --resync to recover",
        ]
        mock_proc = MockStreamingPopen(error_lines, returncode=1)

        with patch("subprocess.Popen", return_value=mock_proc):
            success = worker._execute_sync()

        assert success is False
        assert worker.status == SyncStatus.ERROR
        assert "guardas de seguridad" in worker.last_message.lower()
        # Verify it was never called with resync
        for call_args in mock_rclone.build_bisync_command.call_args_list:
            kwargs = call_args[1] if len(call_args) > 1 else {}
            assert kwargs.get("resync") is not True

    def test_streaming_stale_lock_recovery(self, tmp_path):
        vault = tmp_path / "vault"
        vault.mkdir()
        lock_file = tmp_path / "stale.lck"
        lock_data = {"Session": str(lock_file), "PID": "99999999"}
        lock_file.write_text(json.dumps(lock_data), encoding="utf-8")
        assert lock_file.exists()

        cfg = ConfigData(local_vault_path=str(vault), remote_folder_name="vault", first_sync_done=True)
        mock_rclone = MagicMock()
        mock_rclone.build_bisync_command.return_value = ["mock_rclone"]
        worker = SyncWorker(config=cfg, rclone_manager=mock_rclone)

        proc_fail = MockStreamingPopen(
            [f"ERROR : Bisync critical error: lock file already exists: {lock_file}"],
            returncode=1,
        )
        proc_success = MockStreamingPopen(
            ["Bisync successful"],
            returncode=0,
        )

        with patch("subprocess.Popen", side_effect=[proc_fail, proc_success]):
            success = worker._execute_sync()

        assert success is True
        assert worker.status == SyncStatus.SUCCESS
        assert not lock_file.exists()

    def test_legacy_listeners_receive_notifications_during_streaming(self, tmp_path):
        vault = tmp_path / "vault"
        vault.mkdir()
        cfg = ConfigData(local_vault_path=str(vault), remote_folder_name="vault", first_sync_done=True)
        worker = SyncWorker(config=cfg, rclone_manager=MagicMock())

        notifications = []
        def listener(status: SyncStatus, msg: str):
            notifications.append((status, msg))

        worker.register_listener(listener)

        mock_proc = MockStreamingPopen(["Bisync successful"], returncode=0)
        with patch("subprocess.Popen", return_value=mock_proc):
            success = worker._execute_sync()

        assert success is True
        statuses = [s for s, _ in notifications]
        assert SyncStatus.SYNCING in statuses
        assert SyncStatus.SUCCESS in statuses


class TestManualResyncRecovery:
    GUARD_LINES = [
        "ERROR : Bisync critical error: cannot find prior Path1 or Path2 listings",
        "ERROR : Bisync aborted. Must run --resync to recover.",
    ]

    def _worker(self, tmp_path):
        vault = tmp_path / "vault"
        vault.mkdir()
        cfg = ConfigData(local_vault_path=str(vault), remote_folder_name="vault", first_sync_done=True)
        mock_rclone = MagicMock()
        mock_rclone.build_bisync_command.return_value = ["mock_rclone"]
        return SyncWorker(config=cfg, rclone_manager=mock_rclone), mock_rclone

    def test_guard_abort_sets_needs_resync(self, tmp_path):
        worker, _ = self._worker(tmp_path)
        with patch("subprocess.Popen", return_value=MockStreamingPopen(self.GUARD_LINES, returncode=1)):
            assert worker._execute_sync() is False
        assert worker.needs_resync is True

    def test_requested_resync_runs_once_and_clears_flag(self, tmp_path):
        worker, mock_rclone = self._worker(tmp_path)
        worker.needs_resync = True
        worker._force_resync = True

        with patch("subprocess.Popen", side_effect=lambda *a, **k: MockStreamingPopen(["ok"], returncode=0)):
            assert worker._execute_sync() is True
            assert worker._execute_sync() is True

        resync_flags = [c.kwargs.get("resync") for c in mock_rclone.build_bisync_command.call_args_list]
        assert resync_flags == [True, False]
        assert worker.needs_resync is False

    def test_request_resync_when_stopped_runs_in_background(self, tmp_path):
        worker, mock_rclone = self._worker(tmp_path)
        with patch("subprocess.Popen", side_effect=lambda *a, **k: MockStreamingPopen(["ok"], returncode=0)):
            assert worker.request_resync() is True
            deadline = time.time() + 5
            while not mock_rclone.build_bisync_command.called and time.time() < deadline:
                time.sleep(0.02)
            while worker._sync_lock.locked() and time.time() < deadline:
                time.sleep(0.02)
        assert mock_rclone.build_bisync_command.call_args.kwargs.get("resync") is True

    def test_request_resync_rejected_while_syncing(self, tmp_path):
        worker, _ = self._worker(tmp_path)
        worker._is_syncing = True
        assert worker.request_resync() is False
        assert worker._force_resync is False
