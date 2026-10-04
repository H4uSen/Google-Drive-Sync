"""
Empirical Adversarial Stress Test Suite for Streaming SyncWorker.

Covers:
1. Malformed / corrupted rclone output (binary garbage, invalid UTF-8, complex unicode,
   partial lines, huge lines, non-float percentages).
2. Watchdog timeout and unblocking without zombie processes (open pipes, SIGKILL escalation,
   early stdout/stderr closure, zombie reaping).
3. Rapid concurrent cancellation and worker lifecycle (cancel_sync, stop, restart).
4. External process termination and signal handling (SIGTERM, SIGKILL).
"""
import sys
import os
import time
import signal
import tempfile
import threading
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import psutil
import pytest

from src.core.sync_worker import SyncWorker, SyncStatus
from src.core.config import ConfigData
from src.core.events import EventDispatcher, EventType, FilePayload, ProgressPayload


@pytest.fixture
def mock_config(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    return ConfigData(local_vault_path=str(vault), remote_folder_name="vault", first_sync_done=True)


class TestAdversarialOutputParsing:
    def test_binary_garbage_and_invalid_utf8(self, mock_config):
        """Binary garbage and invalid byte sequences should not crash the stream parser."""
        worker = SyncWorker(config=mock_config, rclone_manager=MagicMock())
        with tempfile.NamedTemporaryFile("wb", delete=False) as f:
            f.write(b"\x00\xff\xfe\x80\x01\x02\x03\n2026/10/02 21:42:56 INFO  : safe_note.md: Copied (new)\n")
            temp_path = f.name

        try:
            cmd = [sys.executable, "-c", f"import sys; sys.stdout.buffer.write(open({repr(temp_path)}, 'rb').read())"]
            ret, out, files, total_bytes, conflicts = worker._stream_subprocess(cmd, timeout=5)
            assert "safe_note.md" in files
            assert ret == 0
        finally:
            os.unlink(temp_path)

    def test_unicode_complex_scripts(self, mock_config):
        """Multi-byte CJK, bidirectional RTL, zero-width joiners, and emoji sequences."""
        worker = SyncWorker(config=mock_config, rclone_manager=MagicMock())
        lines = [
            "2026/10/02 21:42:56 INFO  : 笔记/日本語/한글_sync.md: Copied (new)\n",
            "2026/10/02 21:42:56 INFO  : \u202e\u05e9\u05dc\u05d5\u05dd.md: Copied (new)\n",
            "2026/10/02 21:42:56 INFO  : 👨\u200d👩\u200d👧\u200d👦_family_e\u0301.md: Copied (new)\n",
            "2026/10/02 21:42:56 INFO  : 𝔘𝔫𝔦𝔠𝔬𝔡𝔢.md: Copied (new)\n",
        ]
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as f:
            f.writelines(lines)
            temp_path = f.name

        try:
            cmd = [sys.executable, "-c", f"import sys; sys.stdout.buffer.write(open({repr(temp_path)}, 'rb').read())"]
            ret, out, files, total_bytes, conflicts = worker._stream_subprocess(cmd, timeout=5)
            assert len(files) == 4
            assert "笔记/日本語/한글_sync.md" in files
            assert "\u202e\u05e9\u05dc\u05d5\u05dd.md" in files
        finally:
            os.unlink(temp_path)

    def test_partial_line_without_trailing_newline(self, mock_config):
        """Processes exiting without emitting a final newline character should still have their output parsed."""
        worker = SyncWorker(config=mock_config, rclone_manager=MagicMock())
        cmd = [
            sys.executable,
            "-c",
            "import sys; sys.stdout.write('2026/10/02 21:42:56 INFO  : no_newline.md: Copied (new)')",
        ]
        ret, out, files, total_bytes, conflicts = worker._stream_subprocess(cmd, timeout=5)
        assert "no_newline.md" in files

    def test_huge_line_handling(self, mock_config):
        """A single line of 1MB length should not cause buffer corruption or parser crashes."""
        worker = SyncWorker(config=mock_config, rclone_manager=MagicMock())
        huge_name = "A" * 1000000
        line = f"2026/10/02 21:42:56 INFO  : {huge_name}.md: Copied (new)\n"
        with tempfile.NamedTemporaryFile("w", delete=False) as f:
            f.write(line)
            temp_path = f.name

        try:
            cmd = [sys.executable, "-c", f"import sys; sys.stdout.buffer.write(open({repr(temp_path)}, 'rb').read())"]
            ret, out, files, total_bytes, conflicts = worker._stream_subprocess(cmd, timeout=10)
            assert len(files) == 1
            assert files[0].endswith(".md")
        finally:
            os.unlink(temp_path)

    def test_malformed_star_percentage_does_not_crash(self, mock_config):
        """
        Adversarial line '* file.md: .% / 100%, 10 KB/s' matches FILE_STAR_RE but group(2) is '.'.
        float('.') raises ValueError, which currently crashes _stream_subprocess instead of degrading gracefully.
        """
        worker = SyncWorker(config=mock_config, rclone_manager=MagicMock())
        cmd = [sys.executable, "-c", "print('* notes.md: .% / 100%, 10 KB/s', flush=True)"]
        success, details = worker.run_streaming_sync(cmd=cmd, timeout=5)
        assert success is True

    def test_empty_conflict_filename_line_not_captured_or_emitted(self, mock_config):
        """
        Adversarial warning lines with trailing whitespace or missing target paths
        must NOT produce empty string filenames in seen_conflicts or emit empty ConflictPayload.
        """
        dispatcher = EventDispatcher()
        captured_conflicts = []
        dispatcher.subscribe(
            EventType.CONFLICT_DETECTED,
            lambda ev: captured_conflicts.append(ev.data)
        )
        worker = SyncWorker(config=mock_config, rclone_manager=MagicMock(), event_dispatcher=dispatcher)
        test_lines = [
            "NOTICE: - WARNING           New or changed in both paths                - \n",
            "NOTICE: - WARNING           New or changed in both paths                -\n",
            "NOTICE: - WARNING           New or changed in both paths                -   \t  \n",
            "NOTICE: - WARNING           New or changed in both paths                - valid_conflict_1.md\n",
            "ERROR : : differ\n",
            "ERROR :    : differ on size\n",
            "ERROR : valid_conflict_2.md: files differ\n",
        ]
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as f:
            f.writelines(test_lines)
            temp_path = f.name

        try:
            cmd = [sys.executable, "-c", f"import sys; sys.stdout.write(open({repr(temp_path)}, encoding='utf-8').read())"]
            ret, out, files, total_bytes, conflicts = worker._stream_subprocess(cmd, timeout=5)
            assert "" not in conflicts
            assert None not in conflicts
            assert len(conflicts) == 2
            assert "valid_conflict_1.md" in conflicts
            assert "valid_conflict_2.md" in conflicts
            assert len(captured_conflicts) == 2
            for c in captured_conflicts:
                assert c.filename != ""
                assert c.filename is not None
                assert len(c.filename.strip()) > 0
        finally:
            os.unlink(temp_path)



class TestAdversarialWatchdogAndZombies:
    def test_watchdog_terminates_hanging_process_open_pipe(self, mock_config):
        """Watchdog must terminate hanging child process and unblock within timeout."""
        worker = SyncWorker(config=mock_config, rclone_manager=MagicMock())
        t0 = time.time()
        with pytest.raises(subprocess.TimeoutExpired):
            worker.run_streaming_sync(cmd=["sleep", "30"], timeout=1)
        elapsed = time.time() - t0
        assert elapsed < 3.0

    def test_watchdog_escalates_to_sigkill_when_sigterm_ignored(self, mock_config):
        """When child process ignores SIGTERM, watchdog must escalate to SIGKILL and reap process."""
        worker = SyncWorker(config=mock_config, rclone_manager=MagicMock())
        t0 = time.time()
        with pytest.raises(subprocess.TimeoutExpired):
            worker.run_streaming_sync(cmd=["bash", "-c", "trap '' TERM; sleep 30"], timeout=1)
        elapsed = time.time() - t0
        assert elapsed < 4.5

    def test_watchdog_enforced_when_stdout_closed_early(self, mock_config):
        """
        When child process closes its stdout/stderr descriptors early, readline hits EOF.
        The worker cancels the watchdog timer and blocks on proc.wait() with NO TIMEOUT.
        This test verifies whether the 1-second timeout is honored when fds close early.
        """
        worker = SyncWorker(config=mock_config, rclone_manager=MagicMock())
        t0 = time.time()
        # Process closes fds and sleeps 4s with 1s timeout
        with pytest.raises(subprocess.TimeoutExpired):
            worker.run_streaming_sync(cmd=["bash", "-c", "exec 1>&-; exec 2>&-; sleep 4"], timeout=1)
        elapsed = time.time() - t0
        assert elapsed < 2.5

    def test_no_zombies_on_parser_exception(self, mock_config):
        """
        When a parser exception occurs mid-stream, the child process must be terminated and reaped.
        Currently, unhandled exceptions bypass proc.wait(), leaving defunct zombie processes.
        """
        worker = SyncWorker(config=mock_config, rclone_manager=MagicMock())
        parent_proc = psutil.Process(os.getpid())
        worker.rclone.build_bisync_command.return_value = [
            sys.executable,
            "-c",
            "import time; print('* notes.md: .% / 100%, 10 KB/s', flush=True); time.sleep(1)",
        ]
        worker._execute_sync()
        time.sleep(1.5)
        zombies = [c for c in parent_proc.children(recursive=True) if c.status() == psutil.STATUS_ZOMBIE]
        assert len(zombies) == 0, f"Found zombie processes: {[z.pid for z in zombies]}"


class TestAdversarialCancellationAndSignals:
    def test_rapid_concurrent_cancel_sync(self, mock_config):
        """Rapid concurrent cancel_sync calls during active file transfer streaming."""
        worker = SyncWorker(config=mock_config, rclone_manager=MagicMock())
        py_code = (
            "import sys, time\n"
            "for i in range(200):\n"
            "    print(f'2026/10/02 21:42:56 INFO  : note_{i}.md: Copied (new)', flush=True)\n"
            "    time.sleep(0.005)\n"
        )
        cmd = [sys.executable, "-c", py_code]

        sync_thread = threading.Thread(target=worker.run_streaming_sync, kwargs={"cmd": cmd, "timeout": 15})
        sync_thread.start()
        time.sleep(0.05)

        cancel_errors = []
        def cancel_burst():
            try:
                for _ in range(15):
                    worker.cancel_sync()
                    time.sleep(0.001)
            except Exception as e:
                cancel_errors.append(e)

        threads = [threading.Thread(target=cancel_burst) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        sync_thread.join(timeout=3)
        assert not sync_thread.is_alive()
        assert len(cancel_errors) == 0

    def test_rapid_worker_lifecycle_churn(self, mock_config):
        """Rapidly starting, triggering, cancelling, and stopping the worker loop."""
        worker = SyncWorker(config=mock_config, rclone_manager=MagicMock())
        py_code = (
            "import sys, time\n"
            "for i in range(50):\n"
            "    print(f'* f{i}.md: 50% / 50%, 10 KB/s', flush=True)\n"
            "    time.sleep(0.01)\n"
        )
        worker.rclone.build_bisync_command.return_value = [sys.executable, "-c", py_code]

        worker.start()
        time.sleep(0.02)

        for _ in range(5):
            worker.trigger_now()
            time.sleep(0.01)
            worker.cancel_sync()
            time.sleep(0.01)

        worker.stop()
        assert worker._running is False
        if worker._thread:
            assert not worker._thread.is_alive()

    def test_external_sigterm_handling(self, mock_config):
        """Abrupt SIGTERM sent to the rclone child process from an external process."""
        worker = SyncWorker(config=mock_config, rclone_manager=MagicMock())
        worker.rclone.build_bisync_command.return_value = ["sleep", "15"]

        def killer():
            while worker._process is None:
                time.sleep(0.01)
            time.sleep(0.05)
            if worker._process:
                os.kill(worker._process.pid, signal.SIGTERM)

        kill_thread = threading.Thread(target=killer)
        kill_thread.start()

        success = worker._execute_sync()
        kill_thread.join()

        assert success is False
        assert worker.status == SyncStatus.ERROR

    def test_external_sigkill_handling(self, mock_config):
        """Abrupt SIGKILL sent to the rclone child process from an external process."""
        worker = SyncWorker(config=mock_config, rclone_manager=MagicMock())
        worker.rclone.build_bisync_command.return_value = ["sleep", "15"]

        def killer():
            while worker._process is None:
                time.sleep(0.01)
            time.sleep(0.05)
            if worker._process:
                os.kill(worker._process.pid, signal.SIGKILL)

        kill_thread = threading.Thread(target=killer)
        kill_thread.start()

        success = worker._execute_sync()
        kill_thread.join()

        assert success is False
        assert worker.status == SyncStatus.ERROR

    def test_presync_cancellation_during_ensure_remote_dir(self, mock_config):
        """
        When cancel_sync() is invoked while ensure_remote_dir() is running (pre-sync phase),
        the worker must return failure/cancelled status immediately and NEVER spawn a child process.
        """
        mock_rclone = MagicMock()
        worker = SyncWorker(config=mock_config, rclone_manager=mock_rclone)

        def cancel_during_ensure(folder):
            worker.cancel_sync()

        mock_rclone.ensure_remote_dir.side_effect = cancel_during_ensure

        with patch("subprocess.Popen") as mock_popen:
            success = worker._execute_sync()
            assert success is False
            assert worker.status == SyncStatus.IDLE
            assert "cancelada" in worker.last_message.lower()
            assert not mock_popen.called, "subprocess.Popen must NOT be spawned when cancelled pre-sync"
            assert not mock_rclone.build_bisync_command.called

    def test_presync_cancellation_preserves_state_before_popen(self, mock_config):
        """
        Directly calling _stream_subprocess when worker._cancelled is already True
        must return code 1 immediately without spawning subprocess.Popen.
        """
        worker = SyncWorker(config=mock_config, rclone_manager=MagicMock())
        worker.cancel_sync()

        with patch("subprocess.Popen") as mock_popen:
            ret, out, files, total_bytes, conflicts = worker._stream_subprocess(["echo", "unused"])
            assert ret == 1
            assert "cancelada" in out.lower()
            assert not mock_popen.called

    def test_midstream_rapid_cancellation_under_high_volume_burst(self, mock_config):
        """
        Rapid cancellation burst while stream is processing thousands of lines of output.
        Must terminate the child process promptly without zombies or deadlocks.
        """
        worker = SyncWorker(config=mock_config, rclone_manager=MagicMock())
        burst_code = (
            "import sys\n"
            "for i in range(50000):\n"
            "    sys.stdout.write(f'2026/10/02 21:42:56 INFO  : burst_{i}.md: Copied (new)\\n')\n"
            "    if i % 100 == 0:\n"
            "        sys.stdout.flush()\n"
        )
        cmd = [sys.executable, "-c", burst_code]

        t0 = time.time()
        sync_thread = threading.Thread(target=worker.run_streaming_sync, kwargs={"cmd": cmd, "timeout": 15})
        sync_thread.start()
        time.sleep(0.04)

        cancel_errors = []
        def cancel_burst():
            try:
                for _ in range(30):
                    worker.cancel_sync()
                    time.sleep(0.001)
            except Exception as e:
                cancel_errors.append(e)

        threads = [threading.Thread(target=cancel_burst) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        sync_thread.join(timeout=5)
        elapsed = time.time() - t0

        assert not sync_thread.is_alive(), "Sync thread failed to terminate under rapid cancellation"
        assert len(cancel_errors) == 0
        assert elapsed < 5.0

        parent = psutil.Process(os.getpid())
        zombies = [c for c in parent.children(recursive=True) if c.status() == psutil.STATUS_ZOMBIE]
        assert len(zombies) == 0, f"Found zombie processes: {[z.pid for z in zombies]}"

