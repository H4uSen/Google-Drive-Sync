"""
Sync engine (SyncWorker): how it turns each Sync run into status, history and
events. rclone runs are scripted through FakeLauncher; RcloneManager is stubbed.
"""
import json
import threading
import time

import pytest

from src.core.config import VaultProfile
from src.core.events import EventDispatcher, EventType
from src.core.history_manager import SyncHistoryManager
from src.core.sync_worker import SyncStatus, SyncWorker, clean_error_message, try_recover_stale_lock
from tests.builders import vault_config
from tests.fakes import FakeLauncher, FakeProcess, stub_rclone

GUARD_LINES = [
    "ERROR : Bisync critical error: cannot find prior Path1 or Path2 listings",
    "ERROR : Bisync aborted. Must run --resync to recover.",
]


class Engine:
    """A SyncWorker wired to fakes, plus what tests observe of it."""

    def __init__(self, tmp_path, *processes, first_sync_done=True, remote_folder="vault"):
        vault = tmp_path / "vault"
        vault.mkdir(exist_ok=True)
        self.vault = vault
        self.config = vault_config(vault, remote_folder, name="Notas", first_sync_done=first_sync_done)
        self.rclone = stub_rclone()
        self.launcher = FakeLauncher(*processes)
        self.dispatcher = EventDispatcher()
        self.history = SyncHistoryManager(tmp_path / "history.json")
        self.worker = SyncWorker(
            config=self.config,
            rclone_manager=self.rclone,
            event_dispatcher=self.dispatcher,
            history_manager=self.history,
            launcher=self.launcher,
        )
        self.batches = []
        self.dispatcher.subscribe(EventType.BATCH_COMPLETED, lambda ev: self.batches.append(ev.data))
        self.statuses = []
        self.worker.register_listener(lambda status, msg: self.statuses.append(status))

    def sync(self) -> bool:
        return self.worker._execute_sync()

    @property
    def last_run(self):
        return self.history.get_recent_runs(1)[0]

    def resync_flags(self):
        return ["--resync" in cmd for cmd in self.launcher.commands]


def copied(*names):
    return [f"2026/10/07 10:00:00 INFO  : {n}: Copied (new)" for n in names]


# --- Successful runs ---------------------------------------------------------

def test_successful_run_reports_success_history_and_batch(tmp_path):
    engine = Engine(tmp_path, FakeProcess(copied("a.md", "b.md")))
    (engine.vault / "a.md").write_text("1234", encoding="utf-8")

    assert engine.sync() is True

    assert engine.statuses == [SyncStatus.SYNCING, SyncStatus.SUCCESS]
    run = engine.last_run
    assert (run.status, run.files_transferred, run.bytes_transferred) == ("SUCCESS", ["a.md", "b.md"], 4)
    assert [(b.total_files, b.total_bytes, b.status) for b in engine.batches] == [(2, 4, "SUCCESS")]
    engine.rclone.ensure_remote_dir.assert_called_once_with("vault")


def test_successful_run_marks_the_vault_as_synced(tmp_path):
    engine = Engine(tmp_path)

    engine.sync()

    vault = engine.config.active_vault
    assert (vault.last_sync_status, bool(vault.last_sync_timestamp)) == ("success", True)
    assert engine.last_run.vault_name == "Notas"


def test_conflicts_are_recorded_as_conflict(tmp_path):
    engine = Engine(tmp_path, FakeProcess(["ERROR : note.md: md5 differ"]))

    assert engine.sync() is True

    assert engine.last_run.status == "CONFLICT"
    assert "1 files" in engine.last_run.error_message


def test_first_sync_of_a_vault_is_a_resync_and_later_ones_are_not(tmp_path):
    engine = Engine(tmp_path, first_sync_done=False)

    engine.sync()
    engine.sync()

    assert engine.resync_flags() == [True, False]
    assert engine.config.active_vault.first_sync_done is True


def switch_vault_during_the_run(engine, tmp_path):
    other_dir = tmp_path / "other"
    other_dir.mkdir()
    other = VaultProfile(id="other", name="Otro", local_path=str(other_dir), remote_folder="other")
    engine.config.vaults.append(other)
    engine.rclone.ensure_remote_dir.side_effect = lambda folder: engine.config.set_active_vault("other")
    return other


def test_vault_switched_during_a_run_is_not_marked_as_synced(tmp_path):
    engine = Engine(tmp_path, first_sync_done=False)
    synced = engine.config.active_vault
    other = switch_vault_during_the_run(engine, tmp_path)

    assert engine.sync() is True

    assert engine.launcher.commands[0][2:4] == [str(engine.vault), "gdrive:vault"]
    assert (synced.first_sync_done, synced.last_sync_status) == (True, "success")
    assert (other.first_sync_done, other.last_sync_status, other.last_sync_timestamp) == (False, "idle", "")


def test_history_names_the_vault_that_was_synced_not_the_one_active_after(tmp_path):
    engine = Engine(tmp_path)
    switch_vault_during_the_run(engine, tmp_path)

    engine.sync()

    assert engine.last_run.vault_name == "Notas"


def test_blank_vault_name_is_recorded_as_principal(tmp_path):
    engine = Engine(tmp_path)
    engine.config.active_vault.name = "   "

    engine.sync()

    assert engine.last_run.vault_name == "Principal"


# --- Failed runs -------------------------------------------------------------

def test_rclone_failure_reports_error_and_keeps_partial_files(tmp_path):
    engine = Engine(tmp_path, FakeProcess(
        copied("a.md") + ["2026/10/07 10:00:01 ERROR : Bisync critical error: network down"],
        returncode=1,
    ))

    assert engine.sync() is False

    assert engine.worker.status == SyncStatus.ERROR
    assert "network down" in engine.worker.last_message
    assert (engine.last_run.status, engine.last_run.files_transferred) == ("PARTIAL", ["a.md"])
    assert engine.batches == []


def test_rclone_failure_with_no_files_is_an_error(tmp_path):
    engine = Engine(tmp_path, FakeProcess(["ERROR : Bisync critical error: boom"], returncode=1))

    engine.sync()

    assert engine.last_run.status == "ERROR"


def test_safety_stop_flags_needs_resync_and_never_resyncs_on_its_own(tmp_path):
    engine = Engine(tmp_path, FakeProcess(GUARD_LINES, returncode=2))

    assert engine.sync() is False

    assert engine.worker.needs_resync is True
    assert "guardas de seguridad" in engine.worker.last_message.lower()
    assert engine.resync_flags() == [False]


def test_requested_resync_runs_once_and_clears_needs_resync(tmp_path):
    engine = Engine(tmp_path, FakeProcess(GUARD_LINES, returncode=2))
    engine.sync()

    engine.worker._force_resync = True
    engine.sync()
    engine.sync()

    assert engine.resync_flags() == [False, True, False]
    assert engine.worker.needs_resync is False


def test_stale_lock_from_a_dead_process_is_cleared_and_the_run_retried(tmp_path):
    lock_file = tmp_path / "stale.lck"
    lock_file.write_text(json.dumps({"PID": "99999999"}), encoding="utf-8")
    engine = Engine(
        tmp_path,
        FakeProcess([f"ERROR : Bisync critical error: lock file already exists: {lock_file}"], returncode=1),
        FakeProcess(copied("a.md")),
    )

    assert engine.sync() is True

    assert len(engine.launcher.commands) == 2
    assert not lock_file.exists()
    assert engine.last_run.files_transferred == ["a.md"]


def test_cancel_just_before_the_stale_lock_retry_stops_the_retry(tmp_path):
    lock_file = tmp_path / "stale.lck"
    lock_file.write_text(json.dumps({"PID": "99999999"}), encoding="utf-8")
    engine = Engine(
        tmp_path,
        FakeProcess([f"ERROR : Bisync critical error: lock file already exists: {lock_file}"], returncode=1),
        FakeProcess(copied("a.md")),
    )

    def binary_then_cancel_on_retry():
        if engine.rclone.ensure_rclone_binary.call_count == 2:
            engine.worker.cancel_sync()
        return "/opt/rclone"

    engine.rclone.ensure_rclone_binary.side_effect = binary_then_cancel_on_retry

    assert engine.sync() is False

    assert len(engine.launcher.commands) == 1
    assert engine.worker.status == SyncStatus.IDLE
    assert "cancelada" in engine.worker.last_message.lower()


def test_timed_out_run_reports_error(tmp_path):
    engine = Engine(tmp_path, FakeProcess(hang=True))
    engine.worker.run_timeout = 0.2

    assert engine.sync() is False

    assert engine.worker.status == SyncStatus.ERROR
    assert "tiempo" in engine.worker.last_message.lower()
    assert engine.last_run.status == "ERROR"


def test_unexpected_error_reports_error_and_engine_survives(tmp_path):
    engine = Engine(tmp_path, FakeProcess(copied("a.md")))
    engine.rclone.ensure_remote_dir.side_effect = [Exception("Network offline"), True]

    assert engine.sync() is False
    assert "offline" in engine.worker.last_message.lower()

    assert engine.sync() is True


def test_invalid_remote_folder_reports_error_without_launching(tmp_path):
    engine = Engine(tmp_path, remote_folder="../escape")

    assert engine.sync() is False

    assert engine.worker.status == SyncStatus.ERROR
    assert engine.launcher.commands == []


def test_missing_vault_path_reports_error(tmp_path):
    engine = Engine(tmp_path)
    engine.config.active_vault.local_path = ""

    assert engine.sync() is False
    assert engine.worker.status == SyncStatus.ERROR


def test_nonexistent_vault_path_reports_error(tmp_path):
    engine = Engine(tmp_path)
    engine.config.active_vault.local_path = str(tmp_path / "missing")

    assert engine.sync() is False
    assert "no existe" in engine.worker.last_message.lower()


# --- Cancellation ------------------------------------------------------------

def test_cancel_while_preparing_the_remote_never_launches_rclone(tmp_path):
    engine = Engine(tmp_path)
    engine.rclone.ensure_remote_dir.side_effect = lambda folder: engine.worker.cancel_sync()

    assert engine.sync() is False

    assert engine.launcher.commands == []
    assert engine.worker.status == SyncStatus.IDLE
    assert "cancelada" in engine.worker.last_message.lower()
    assert engine.last_run.status == "PARTIAL"


def test_cancel_during_a_run_stops_rclone(tmp_path):
    proc = FakeProcess(copied("a.md"), hang=True)
    engine = Engine(tmp_path, proc)
    result = {}
    t = threading.Thread(target=lambda: result.setdefault("ok", engine.sync()))
    t.start()

    assert proc.drained.wait(timeout=2)
    engine.worker.cancel_sync()
    t.join(timeout=2)

    assert result["ok"] is False
    assert proc.terminated
    assert engine.worker.status == SyncStatus.IDLE
    assert (engine.last_run.status, engine.last_run.files_transferred) == ("PARTIAL", ["a.md"])


def test_stop_cancels_the_active_run(tmp_path):
    proc = FakeProcess(hang=True)
    engine = Engine(tmp_path, proc)
    engine.worker.start()

    assert proc.drained.wait(timeout=2)
    engine.worker.stop()

    assert proc.terminated
    assert engine.worker._running is False


# --- Engine control ----------------------------------------------------------

def test_pause_and_resume_report_status(tmp_path):
    engine = Engine(tmp_path)

    engine.worker.pause()
    assert engine.worker.status == SyncStatus.PAUSED
    engine.worker.resume()
    assert engine.worker.status == SyncStatus.IDLE


def test_trigger_is_rejected_while_a_run_is_active(tmp_path):
    engine = Engine(tmp_path)
    engine.worker._is_syncing = True

    assert engine.worker.trigger_now() is False


def test_request_resync_when_stopped_runs_in_background(tmp_path):
    engine = Engine(tmp_path)

    assert engine.worker.request_resync() is True

    deadline = time.time() + 5
    while not engine.launcher.commands and time.time() < deadline:
        time.sleep(0.02)
    assert engine.resync_flags() == [True]


def test_request_resync_is_rejected_while_syncing(tmp_path):
    engine = Engine(tmp_path)
    engine.worker._is_syncing = True

    assert engine.worker.request_resync() is False
    assert engine.worker._force_resync is False


def test_changes_during_a_run_trigger_another_run_after_it(tmp_path):
    engine = Engine(tmp_path)
    engine.worker._pending_sync = True

    engine.sync()

    assert engine.worker._pending_sync is False
    assert engine.worker._wakeup_event.is_set()


# --- Error text helpers the engine relies on ---------------------------------

def test_clean_error_message_strips_ansi():
    result = clean_error_message("\x1b[0m\x1b[91mrclone deletefile \"/some/path.lck\"\x1b[0m")

    assert "\x1b" not in result
    assert "rclone deletefile" in result


def test_stale_lock_of_a_dead_process_is_removed(tmp_path):
    lock_file = tmp_path / "test.lck"
    lock_file.write_text(json.dumps({"PID": "99999999"}), encoding="utf-8")

    assert try_recover_stale_lock(f"rclone deletefile \"{lock_file}\"") is True
    assert not lock_file.exists()


def test_lock_of_a_live_process_is_kept(tmp_path):
    import os

    lock_file = tmp_path / "test.lck"
    lock_file.write_text(json.dumps({"PID": str(os.getpid())}), encoding="utf-8")

    assert try_recover_stale_lock(f"lock file already exists: {lock_file}") is False
    assert lock_file.exists()


def test_rapid_start_trigger_cancel_stop_leaves_no_run_behind(tmp_path):
    engine = Engine(tmp_path, *[FakeProcess(copied("a.md"), delay_per_line=0.01) for _ in range(10)])

    engine.worker.start()
    for _ in range(5):
        engine.worker.trigger_now()
        engine.worker.cancel_sync()
    engine.worker.stop()

    assert engine.worker._running is False
    assert not engine.worker._thread.is_alive()
    assert all(p.closed for p in engine.launcher.launched)
