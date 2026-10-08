"""
The production process adapter (`popen_launcher`), tested against real processes:
the one thing scripted fakes cannot verify. POSIX only (process groups, signals).
"""
import os
import stat
import subprocess
import sys
import threading
import time

import psutil
import pytest

from src.core.sync_run import SyncRequest, SyncRun, popen_launcher

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX process groups")


def no_zombie_children():
    me = psutil.Process(os.getpid())
    return not [c for c in me.children(recursive=True) if c.status() == psutil.STATUS_ZOMBIE]


def test_streams_lines_including_invalid_utf8_and_a_final_partial_line():
    proc = popen_launcher([
        sys.executable, "-c",
        "import sys; sys.stdout.buffer.write(b'\\xff\\xfe garbage\\nlast line without newline')",
    ])

    lines = list(iter(proc.readline, ""))
    code = proc.wait(timeout=5)
    proc.close()

    assert lines == ["�� garbage\n", "last line without newline"]
    assert code == 0


def test_wait_times_out_when_process_closes_output_but_keeps_running():
    proc = popen_launcher(["bash", "-c", "exec 1>&-; exec 2>&-; sleep 30"])
    assert proc.readline() == ""

    with pytest.raises(subprocess.TimeoutExpired):
        proc.wait(timeout=0.3)

    proc.terminate()
    proc.close()


def test_terminate_escalates_to_kill_when_sigterm_is_ignored():
    proc = popen_launcher(["bash", "-c", "trap '' TERM; echo ready; sleep 30"])
    assert proc.readline() == "ready\n"

    t0 = time.time()
    proc.terminate()

    assert proc.wait(timeout=1) != 0
    assert time.time() - t0 < 4.5
    proc.close()


def test_terminate_stops_the_whole_process_group():
    proc = popen_launcher(["bash", "-c", "sleep 30 & echo $!; wait"])
    grandchild = psutil.Process(int(proc.readline()))

    proc.terminate()
    proc.close()

    grandchild.wait(timeout=3)
    assert not grandchild.is_running() or grandchild.status() == psutil.STATUS_ZOMBIE
    assert no_zombie_children()


def test_terminate_after_exit_is_harmless():
    proc = popen_launcher(["true"])
    proc.wait(timeout=5)

    proc.terminate()
    proc.terminate()
    proc.close()

    assert no_zombie_children()


@pytest.fixture
def fake_rclone(tmp_path):
    """A stand-in rclone binary: ignores its arguments and runs `body`."""
    def make(body: str) -> str:
        path = tmp_path / "rclone"
        path.write_text(f"#!/usr/bin/env bash\n{body}\n", encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IEXEC)
        return str(path)
    return make


def real_run(tmp_path, binary, timeout=900):
    vault = tmp_path / "vault"
    vault.mkdir(exist_ok=True)
    return SyncRun(
        SyncRequest(str(vault), "Vault", timeout=timeout),
        launcher=popen_launcher,
        rclone_binary=binary,
        filters_file=tmp_path / "filters.txt",
    )


def test_real_run_reports_rclone_output(tmp_path, fake_rclone):
    binary = fake_rclone("echo '2026/10/07 10:00:00 INFO  : a.md: Copied (new)'; exit 0")

    result = real_run(tmp_path, binary).execute()

    assert result.ok
    assert result.files == ["a.md"]


def test_real_run_hanging_past_its_deadline_is_stopped_without_zombies(tmp_path, fake_rclone):
    binary = fake_rclone("trap '' TERM; sleep 30")

    t0 = time.time()
    result = real_run(tmp_path, binary, timeout=0.5).execute()

    assert result.timed_out
    assert time.time() - t0 < 4.5
    assert no_zombie_children()


def test_real_run_survives_a_burst_of_concurrent_cancels(tmp_path, fake_rclone):
    binary = fake_rclone(
        "for i in $(seq 1 50000); do echo \"2026/10/02 21:42:56 INFO  : burst_$i.md: Copied (new)\"; done"
    )
    run = real_run(tmp_path, binary)
    holder = {}
    sync_thread = threading.Thread(target=lambda: holder.setdefault("result", run.execute()))
    sync_thread.start()
    time.sleep(0.05)

    errors = []

    def burst():
        try:
            for _ in range(30):
                run.cancel()
        except Exception as e:
            errors.append(e)

    cancellers = [threading.Thread(target=burst) for _ in range(8)]
    for t in cancellers:
        t.start()
    for t in cancellers:
        t.join()
    sync_thread.join(timeout=5)

    assert not sync_thread.is_alive()
    assert errors == []
    assert holder["result"].cancelled
    assert no_zombie_children()
