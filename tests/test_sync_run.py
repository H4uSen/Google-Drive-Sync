"""
Sync run: one rclone bisync pass for one Vault, tested through its interface
with scripted processes (tests/fakes.py).
"""
import pytest

from src.core.sync_run import SyncRequest, SyncRun
from tests.fakes import FakeLauncher, FakeProcess


@pytest.fixture
def vault(tmp_path):
    path = tmp_path / "vault"
    path.mkdir()
    return path


def make_run(vault, launcher, *, resync=False, timeout=900, dispatcher=None, tmp_filters=None):
    request = SyncRequest(
        local_path=str(vault),
        remote_folder="MyVault",
        resync=resync,
        timeout=timeout,
    )
    return SyncRun(
        request,
        launcher=launcher,
        rclone_binary="/opt/rclone",
        filters_file=tmp_filters or vault.parent / "filters.txt",
        dispatcher=dispatcher,
    )


def test_run_reports_files_rclone_copied(vault):
    launcher = FakeLauncher(FakeProcess([
        "2026/10/07 10:00:00 INFO  : Notes/Todo.md: Copied (new)",
        "2026/10/07 10:00:01 INFO  : Daily/2026-10-07.md: Copied (replaced existing)",
    ]))

    result = make_run(vault, launcher).execute()

    assert result.ok
    assert result.returncode == 0
    assert result.files == ["Notes/Todo.md", "Daily/2026-10-07.md"]
    assert launcher.commands[0][:4] == ["/opt/rclone", "bisync", str(vault), "gdrive:MyVault"]


def test_file_reported_twice_is_counted_once_with_its_local_size(vault):
    (vault / "Todo.md").write_text("12345", encoding="utf-8")
    launcher = FakeLauncher(FakeProcess([
        "* Todo.md: 100% /100%, 50 KiB/s",
        "2026/10/07 10:00:00 INFO  : Todo.md: Copied (new)",
        "2026/10/07 10:00:00 INFO  : Todo.md: Copied (new)",
    ]))

    result = make_run(vault, launcher).execute()

    assert result.files == ["Todo.md"]
    assert result.total_bytes == 5


@pytest.fixture
def events():
    from src.core.events import EventDispatcher, EventType

    dispatcher = EventDispatcher()
    seen = {t: [] for t in EventType}
    for t in EventType:
        dispatcher.subscribe(t, lambda ev, t=t: seen[t].append(ev.data))
    seen["dispatcher"] = dispatcher
    return seen


def test_each_kind_of_transfer_line_publishes_a_file_event(vault, events):
    from src.core.events import EventType

    launcher = FakeLauncher(FakeProcess([
        "2026/10/02 21:42:56 INFO  : note1.md: Copied (new)",
        "2026/10/02 21:42:56 INFO  : note2.md: Copied (replaced)",
        "2026/10/02 21:43:57 INFO  : old.md: Deleted",
        "2026/10/02 21:43:23 INFO  : moved.md: Moved (server-side) to: moved_remote.md",
        "* Notes/Project.md: 100% /100%, 50 KiB/s",
    ]))

    make_run(vault, launcher, dispatcher=events["dispatcher"]).execute()

    files = events[EventType.FILE_TRANSFERRED]
    assert [(f.filename, f.action) for f in files] == [
        ("note1.md", "Copied (new)"),
        ("note2.md", "Copied (replaced)"),
        ("old.md", "Deleted"),
        ("moved.md", "Moved (server-side) to: moved_remote.md"),
        ("Notes/Project.md", "transferred"),
    ]


def test_progress_lines_publish_percentage_speed_and_eta(vault, events):
    from src.core.events import EventType

    launcher = FakeLauncher(FakeProcess([
        "Transferred:   \t        2.450 MiB / 10.000 MiB, 24%, 1.2 MiB/s, ETA 6s",
        "Transferred: 500 KiB / 1 MiB, 50%, 100 KiB/s",
        "* Notes/Project.md: 100% /100%, 50 KiB/s",
        "* broken.md: .% / 100%, 10 KB/s",
    ]))

    make_run(vault, launcher, dispatcher=events["dispatcher"]).execute()

    progress = events[EventType.PROGRESS_UPDATED]
    assert (progress[0].percentage, progress[0].speed_str, progress[0].eta_str) == (24.0, "1.2 MiB/s", "6s")
    assert (progress[0].transferred_bytes, progress[0].total_bytes) == (2569011, 10485760)
    assert (progress[1].percentage, progress[1].eta_str) == (50.0, None)
    assert (progress[2].percentage, progress[2].current_file) == (100.0, "Notes/Project.md")
    assert progress[3].percentage == 0.0


def test_conflicts_are_reported_once_per_file_and_never_blank(vault, events):
    from src.core.events import EventType

    launcher = FakeLauncher(FakeProcess([
        "2026/10/02 21:43:23 NOTICE: - WARNING           New or changed in both paths                - note0.md",
        "2026/10/02 21:43:23 ERROR : note0.md: md5 differ",
        "NOTICE: - WARNING           New or changed in both paths                - ",
        "NOTICE: - WARNING           New or changed in both paths                -   \t  ",
        "ERROR :    : differ on size",
        "ERROR : other.md: files differ",
    ]))

    result = make_run(vault, launcher, dispatcher=events["dispatcher"]).execute()

    assert result.conflicts == ["note0.md", "other.md"]
    assert [c.filename for c in events[EventType.CONFLICT_DETECTED]] == ["note0.md", "other.md"]


def test_every_output_line_is_published_as_a_log_with_its_level(vault, events):
    from src.core.events import EventType

    launcher = FakeLauncher(FakeProcess(["Normal informational log line", "", "ERROR : Some rclone failure"]))

    make_run(vault, launcher, dispatcher=events["dispatcher"]).execute()

    logs = events[EventType.LOG_EMITTED]
    assert [(l.level, l.message) for l in logs] == [
        ("INFO", "Normal informational log line"),
        ("ERROR", "ERROR : Some rclone failure"),
    ]


def test_raw_output_is_kept_and_ansi_codes_do_not_break_parsing(vault):
    launcher = FakeLauncher(FakeProcess(["\x1b[32m2026/10/02 21:42:56 INFO  : 笔记/한글.md: Copied (new)\x1b[0m"], returncode=0))

    result = make_run(vault, launcher).execute()

    assert result.files == ["笔记/한글.md"]
    assert "\x1b[32m" in result.output


def test_failed_rclone_exit_is_reported_not_raised(vault):
    launcher = FakeLauncher(FakeProcess(["ERROR : Bisync critical error: boom"], returncode=7))

    result = make_run(vault, launcher).execute()

    assert result.returncode == 7
    assert not result.ok
    assert "Bisync critical error" in result.output


def run_with(request, tmp_path):
    launcher = FakeLauncher()
    run = SyncRun(request, launcher=launcher, rclone_binary="/usr/bin/rclone", filters_file=tmp_path / "filters.txt")
    return run, launcher


def test_bisync_command_carries_the_safety_flags(tmp_path):
    run, launcher = run_with(SyncRequest("/home/user/My Obsidian Vault", "My Remote Vault"), tmp_path)

    run.execute()

    assert launcher.commands == [[
        "/usr/bin/rclone", "bisync", "/home/user/My Obsidian Vault", "gdrive:My Remote Vault",
        "--filters-file", str(tmp_path / "filters.txt"),
        "--drive-chunk-size", "32M",
        "--conflict-resolve", "none",
        "--conflict-loser", "pathname",
        "--tpslimit", "8",
        "--max-lock", "15m",
        "--color", "never",
        "--retries", "3",
        "-v",
    ]]
    assert (tmp_path / "filters.txt").exists()


def test_resync_request_adds_resync_flag(tmp_path):
    run, launcher = run_with(SyncRequest("/home/user/vault", "ObsidianVault", resync=True), tmp_path)

    run.execute()

    assert launcher.commands[0][-1] == "--resync"


@pytest.mark.parametrize("remote", ["", "/", "  ", ".", "..", "../notes", "/nested/../"])
def test_invalid_remote_folder_is_rejected_before_launch(remote, tmp_path):
    run, launcher = run_with(SyncRequest("/home/user/vault", remote), tmp_path)

    with pytest.raises(ValueError, match="inválida"):
        run.execute()
    assert launcher.commands == []


def test_system_root_vault_is_rejected_before_launch(tmp_path):
    run, launcher = run_with(SyncRequest("/", "ObsidianVault"), tmp_path)

    with pytest.raises(ValueError, match="raíz"):
        run.execute()
    assert launcher.commands == []


def test_run_cancelled_before_execute_never_launches(vault):
    launcher = FakeLauncher()
    run = make_run(vault, launcher)

    run.cancel()
    result = run.execute()

    assert run.cancelled
    assert result.cancelled
    assert result.returncode is None
    assert not result.ok
    assert launcher.commands == []


def test_cancel_during_run_terminates_rclone_and_keeps_partial_files(vault):
    import threading

    proc = FakeProcess(["2026/10/07 10:00:00 INFO  : first.md: Copied (new)"], hang=True)
    run = make_run(vault, FakeLauncher(proc))
    holder = {}
    worker = threading.Thread(target=lambda: holder.setdefault("result", run.execute()))
    worker.start()

    assert proc.drained.wait(timeout=2)
    run.cancel()
    worker.join(timeout=2)

    assert not worker.is_alive()
    result = holder["result"]
    assert result.cancelled
    assert not result.ok
    assert result.files == ["first.md"]
    assert proc.terminated
    assert proc.closed


def test_rclone_hanging_with_open_output_is_stopped_at_the_deadline(vault):
    proc = FakeProcess(["2026/10/07 10:00:00 INFO  : first.md: Copied (new)"], hang=True)

    result = make_run(vault, FakeLauncher(proc), timeout=0.2).execute()

    assert result.timed_out
    assert not result.cancelled
    assert not result.ok
    assert result.files == ["first.md"]
    assert proc.terminated


def test_rclone_that_closes_output_but_never_exits_is_stopped_at_the_deadline(vault):
    proc = FakeProcess([], hang_on_exit=True)

    result = make_run(vault, FakeLauncher(proc), timeout=0.2).execute()

    assert result.timed_out
    assert proc.terminated
    assert proc.closed


def test_rclone_is_stopped_when_reading_its_output_fails(vault):
    class BrokenPipeProcess(FakeProcess):
        def readline(self):
            raise OSError("pipe broke")

    proc = BrokenPipeProcess(hang=True)

    with pytest.raises(OSError, match="pipe broke"):
        make_run(vault, FakeLauncher(proc)).execute()
    assert proc.terminated
    assert proc.closed


def test_a_one_megabyte_line_is_parsed(vault):
    name = "A" * 1_000_000 + ".md"
    launcher = FakeLauncher(FakeProcess([f"2026/10/02 21:42:56 INFO  : {name}: Copied (new)"]))

    result = make_run(vault, launcher).execute()

    assert result.files == [name]
