"""
Sync run: one rclone bisync pass between a Vault's local folder and its Drive folder.

The process is started through a launcher (`popen_launcher` in production), so the
whole run (command building, streaming, parsing, timeout, cancellation) can be
driven by scripted processes in tests.
"""
from __future__ import annotations

import logging
import os
import re
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional, Protocol

from src.core.events import (
    EventType,
    ProgressPayload,
    FilePayload,
    ConflictPayload,
    LogPayload,
)
from src.core.rclone_manager import sanitize_remote_folder, validate_local_path, write_filters_file

logger = logging.getLogger(__name__)

ANSI_ESCAPE_RE = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')

FILE_TRANSFER_RE = re.compile(
    r"^(?:\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2} )?(?:INFO|NOTICE)\s*:\s*(.+?):\s*(Copied(?:\s*\([^)]+\))?|Deleted|Moved\s*\(server-side\)\s*to:\s*(.+))$"
)
FILE_STAR_RE = re.compile(
    r"^\*\s*(.+?):\s*([\d\.]+)%\s*/\s*([\d\.]+)%,\s*(.*)$"
)
PROGRESS_BYTES_RE = re.compile(
    r"(?:Transferred:\s+)?(?:\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2} INFO\s*:\s*)?"
    r"([\d\.]+\s*[KMGTPE]?i?B)\s*/\s*([\d\.]+\s*[KMGTPE]?i?B),\s*([\d\.]+)%,\s*([^,]+)(?:,\s*ETA\s*([^\s]+))?"
)
CONFLICT_WARN_RE = re.compile(
    r"NOTICE:\s*-\s*WARNING\s+New or changed in both paths\s+-\s*(\S.*)$"
)
CONFLICT_DIFFER_RE = re.compile(
    r"ERROR\s*:\s*(.+?):\s*(\S+\s+differ.*)$"
)


def parse_byte_size(size_str: str) -> int:
    """Parse human-readable byte string (e.g. '2.450 MiB', '500 KiB', '22 B') to integer bytes."""
    units = {
        'B': 1,
        'K': 1024, 'KB': 1000, 'KIB': 1024,
        'M': 1024**2, 'MB': 1000**2, 'MIB': 1024**2,
        'G': 1024**3, 'GB': 1000**3, 'GIB': 1024**3,
        'T': 1024**4, 'TB': 1000**4, 'TIB': 1024**4,
    }
    m = re.match(r"^([\d\.]+)\s*([A-Za-z]+)?$", size_str.strip())
    if not m:
        return 0
    val_str, unit = m.groups()
    try:
        val = float(val_str)
    except ValueError:
        return 0
    return int(val * units.get((unit or 'B').upper(), 1))


class RunningProcess(Protocol):
    """A started rclone process. readline() returns "" at end of output;
    wait() raises subprocess.TimeoutExpired; terminate() must leave the process
    exited (escalating to a kill if needed) and be safe to call more than once."""

    def readline(self) -> str: ...
    def wait(self, timeout: Optional[float] = None) -> int: ...
    def terminate(self) -> None: ...
    def close(self) -> None: ...


Launcher = Callable[[list[str]], RunningProcess]


class PopenProcess:
    """RunningProcess over subprocess.Popen, in its own session so terminate()
    reaches every process rclone spawned."""

    def __init__(self, cmd: list[str]):
        self._popen = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            encoding="utf-8",
            errors="replace",
            start_new_session=(sys.platform != "win32"),
        )

    def readline(self) -> str:
        return self._popen.stdout.readline() if self._popen.stdout else ""

    def wait(self, timeout: Optional[float] = None) -> int:
        return self._popen.wait(timeout=timeout)

    def _signal_group(self, sig: int, fallback: Callable[[], None]) -> None:
        if hasattr(os, "killpg") and os.name != "nt":
            try:
                os.killpg(os.getpgid(self._popen.pid), sig)
                return
            except (ProcessLookupError, PermissionError):
                pass
        fallback()

    def terminate(self, grace: float = 2.0) -> None:
        """SIGTERM the process group, then SIGKILL it if it outlives `grace` seconds."""
        if self._popen.poll() is not None:
            return
        try:
            self._signal_group(signal.SIGTERM, self._popen.terminate)
            try:
                self._popen.wait(timeout=grace)
            except subprocess.TimeoutExpired:
                logger.warning(f"Proceso rclone {self._popen.pid} no respondió a SIGTERM; forzando SIGKILL.")
                self._kill()
        except Exception as e:
            logger.debug(f"Error terminando proceso: {e}")

    def _kill(self) -> None:
        if self._popen.poll() is not None:
            return
        try:
            self._signal_group(getattr(signal, "SIGKILL", signal.SIGTERM), self._popen.kill)
            self._popen.wait(timeout=1.0)
        except Exception as e:
            logger.debug(f"Error matando proceso: {e}")

    def close(self) -> None:
        if self._popen.stdout:
            try:
                self._popen.stdout.close()
            except Exception:
                pass


def popen_launcher(cmd: list[str]) -> RunningProcess:
    return PopenProcess(cmd)


@dataclass(frozen=True)
class SyncRequest:
    local_path: str
    remote_folder: str
    resync: bool = False
    timeout: float = 900


@dataclass
class SyncRunResult:
    returncode: Optional[int]
    output: str = ""
    files: list[str] = field(default_factory=list)
    total_bytes: int = 0
    conflicts: list[str] = field(default_factory=list)
    timed_out: bool = False
    cancelled: bool = False
    elapsed_seconds: float = 0.0

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out and not self.cancelled


class SyncRun:
    def __init__(
        self,
        request: SyncRequest,
        *,
        launcher: Launcher,
        rclone_binary: str,
        filters_file: Path,
        dispatcher=None,
    ):
        self.request = request
        self._launcher = launcher
        self._rclone_binary = rclone_binary
        self._filters_file = Path(filters_file)
        self._dispatcher = dispatcher
        self._lock = threading.Lock()
        self._cancelled = False
        self._proc: Optional[RunningProcess] = None

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def cancel(self) -> None:
        """Thread-safe. Before execute(), the run will never launch rclone."""
        with self._lock:
            self._cancelled = True
            proc = self._proc
        if proc is not None:
            logger.info("Cancelando proceso rclone activo...")
            proc.terminate()

    def _command(self) -> list[str]:
        validate_local_path(self.request.local_path)
        remote = sanitize_remote_folder(self.request.remote_folder)
        if not self._filters_file.exists():
            write_filters_file(self._filters_file)
        cmd = [
            self._rclone_binary,
            "bisync",
            str(self.request.local_path),
            f"gdrive:{remote}",
            "--filters-file", str(self._filters_file),
            "--drive-chunk-size", "32M",
            "--conflict-resolve", "none",
            "--conflict-loser", "pathname",
            "--tpslimit", "8",
            "--max-lock", "15m",
            "--color", "never",
            "--retries", "3",
            "-v",
        ]
        if self.request.resync:
            cmd.append("--resync")
        return cmd

    def _emit(self, event_type: EventType, payload) -> None:
        if self._dispatcher is None:
            return
        try:
            self._dispatcher.emit(event_type, payload)
        except Exception as e:
            logger.error(f"EventDispatcher emit error: {e}")

    def _local_size(self, filename: str) -> int:
        try:
            path = Path(self.request.local_path) / filename
            return path.stat().st_size if path.is_file() else 0
        except (OSError, ValueError):
            return 0

    def _parse_line(self, line: str, result: SyncRunResult, sized: set[str]) -> None:
        level = "ERROR" if ("ERROR" in line or "Fatal" in line) else "INFO"
        self._emit(EventType.LOG_EMITTED, LogPayload(level=level, message=line, timestamp=time.time()))

        for regex, details in (
            (CONFLICT_WARN_RE, lambda m: "Modificado concurrentemente en ambos extremos"),
            (CONFLICT_DIFFER_RE, lambda m: f"Divergencia de contenido ({m.group(2).strip()})"),
        ):
            m = regex.search(line)
            if m:
                cfile = m.group(1).strip()
                if cfile and cfile not in result.conflicts:
                    result.conflicts.append(cfile)
                    self._emit(EventType.CONFLICT_DETECTED, ConflictPayload(filename=cfile, details=details(m)))

        m_file = FILE_TRANSFER_RE.search(line)
        if m_file:
            fname = m_file.group(1).strip()
            if not fname.startswith(("- Path", "Path1", "Path2", "- WARNING")):
                size = 0
                if fname not in sized:
                    sized.add(fname)
                    size = self._local_size(fname)
                    result.total_bytes += size
                if fname not in result.files:
                    result.files.append(fname)
                    self._emit(EventType.FILE_TRANSFERRED, FilePayload(
                        filename=fname,
                        size=size,
                        action=m_file.group(2).strip(),
                        vault_name=self.request.local_path,
                    ))

        m_star = FILE_STAR_RE.match(line)
        if m_star:
            sfname = m_star.group(1).strip()
            try:
                spct = float(m_star.group(2))
            except ValueError:
                spct = 0.0
            if sfname not in result.files:
                result.files.append(sfname)
                self._emit(EventType.FILE_TRANSFERRED, FilePayload(
                    filename=sfname,
                    size=0,
                    action="transferred",
                    vault_name=self.request.local_path,
                ))
            self._emit(EventType.PROGRESS_UPDATED, ProgressPayload(
                percentage=spct,
                speed_str=m_star.group(4).strip(),
                current_file=sfname,
            ))

        m_prog = PROGRESS_BYTES_RE.search(line)
        if m_prog:
            t_str, tot_str, pct_str, spd_str, eta_str = m_prog.groups()
            try:
                pct_val = float(pct_str)
            except ValueError:
                pct_val = 0.0
            self._emit(EventType.PROGRESS_UPDATED, ProgressPayload(
                transferred_bytes=parse_byte_size(t_str),
                total_bytes=parse_byte_size(tot_str),
                percentage=pct_val,
                speed_str=spd_str.strip() if spd_str else "",
                eta_str=eta_str.strip() if eta_str else None,
            ))

    def execute(self) -> SyncRunResult:
        start = time.time()
        cmd = self._command()
        result = SyncRunResult(returncode=None)
        with self._lock:
            if self._cancelled:
                result.cancelled = True
                return result
            proc = self._proc = self._launcher(cmd)
        lines: list[str] = []
        sized: set[str] = set()
        timed_out = threading.Event()

        def on_deadline():
            timed_out.set()
            logger.error(f"Sincronización cancelada por timeout de {self.request.timeout}s")
            proc.terminate()

        timer = threading.Timer(self.request.timeout, on_deadline)
        timer.daemon = True
        timer.start()
        try:
            for raw in iter(proc.readline, ""):
                lines.append(raw)
                line = ANSI_ESCAPE_RE.sub("", raw).strip()
                if line:
                    self._parse_line(line, result, sized)
                if self._cancelled:
                    break
            if self._cancelled:
                proc.terminate()
            remaining = max(0.1, self.request.timeout - (time.time() - start))
            try:
                result.returncode = proc.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                timed_out.set()
                proc.terminate()
                result.returncode = proc.wait()
        except BaseException:
            proc.terminate()
            raise
        finally:
            timer.cancel()
            with self._lock:
                self._proc = None
            proc.close()
        result.cancelled = self._cancelled
        result.timed_out = timed_out.is_set() and not result.cancelled
        result.output = "".join(lines)
        result.elapsed_seconds = time.time() - start
        return result
