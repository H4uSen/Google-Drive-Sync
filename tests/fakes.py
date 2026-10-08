"""
Test adapters for the Sync run process seam.

FakeLauncher stands in for `popen_launcher`: it records each command and hands
out scripted FakeProcess instances in order.
"""
import subprocess
import threading
import time
from unittest.mock import MagicMock

from src.core.rclone_manager import RcloneManager


class FakeProcess:
    """A scripted rclone process: yields `lines`, then exits with `returncode`.

    hang=True keeps the output open after the scripted lines until the process
    is terminated, like an rclone stuck on the network.
    hang_on_exit=True closes the output but never exits until terminated.
    """

    def __init__(self, lines=(), returncode=0, hang=False, hang_on_exit=False, delay_per_line=0.0):
        self._lines = [l if l.endswith("\n") else l + "\n" for l in lines]
        self.returncode = returncode
        self.hang = hang
        self.hang_on_exit = hang_on_exit
        self.delay_per_line = delay_per_line
        self.terminated = False
        self.closed = False
        self._stopped = threading.Event()
        # Set once every scripted line has been read.
        self.drained = threading.Event()

    def readline(self) -> str:
        if self._stopped.is_set():
            return ""
        if self._lines:
            if self.delay_per_line:
                time.sleep(self.delay_per_line)
            return self._lines.pop(0)
        self.drained.set()
        if self.hang:
            self._stopped.wait()
        return ""

    def wait(self, timeout=None) -> int:
        if (self.hang or self.hang_on_exit) and not self._stopped.wait(timeout):
            raise subprocess.TimeoutExpired(cmd="rclone", timeout=timeout)
        return -15 if self.terminated else self.returncode

    def terminate(self):
        self.terminated = True
        self._stopped.set()

    def close(self):
        self.closed = True


class FakeLauncher:
    """Hands out the given processes in order; extra launches get a clean exit."""

    def __init__(self, *processes):
        self._processes = list(processes)
        self.commands = []
        self.launched = []

    def __call__(self, cmd):
        self.commands.append(list(cmd))
        proc = self._processes.pop(0) if self._processes else FakeProcess()
        self.launched.append(proc)
        return proc


def stub_rclone(binary="/opt/rclone"):
    """RcloneManager stand-in for the Sync engine: no binary lookup, no remote calls."""
    rclone = MagicMock(spec=RcloneManager)
    rclone.ensure_rclone_binary.return_value = binary
    rclone.ensure_remote_dir.return_value = True
    return rclone
