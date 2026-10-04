"""
GuiLogHandler and LogEntry diagnostic components for Obsidian Google Drive Sync.
Adheres to the GuiLogHandler Contract defined in PROJECT.md (Features F-10, F-11, F-12, F-13).
"""
from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass
from datetime import datetime
import os
from pathlib import Path
import sys
import threading
from typing import List, Optional, Callable, Union
import uuid


@dataclass
class LogEntry:
    timestamp: str             # e.g. "2026-10-03 14:32:10"
    level: str                 # e.g. "INFO", "WARNING", "ERROR"
    message: str               # Log message text
    logger_name: Optional[str] = None

    def format(self) -> str:
        """Format entry into standard human-readable single/multiline log string."""
        return f"{self.timestamp} [{self.level}] {self.message}"

    def __str__(self) -> str:
        return self.format()

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "level": self.level,
            "message": self.message,
            "logger_name": self.logger_name,
        }


class GuiLogHandler(logging.Handler):
    """
    Thread-safe in-memory ring-buffer logging handler supporting:
    - Bounded memory footprint (deque maxlen)
    - Exact level filtering (ALL, INFO, WARNING, ERROR, etc.)
    - Case-insensitive substring search
    - Atomic log file export
    - Observer listener notifications for UI streaming
    """

    def __init__(self, max_entries: int = 1000) -> None:
        super().__init__()
        self.setLevel(logging.DEBUG)
        if logging.root.level > logging.DEBUG:
            logging.root.setLevel(logging.DEBUG)
        self.max_entries = max(1, int(max_entries))
        self._lock = threading.RLock()
        self._buffer: deque[LogEntry] = deque(maxlen=self.max_entries)
        self._listeners: List[Callable[[LogEntry], None]] = []


    def emit(self, record: logging.LogRecord) -> None:
        """
        Extract structured data from LogRecord and append to in-memory buffer.
        Never raises exceptions to caller (follows logging.Handler contract).
        """
        try:
            # Timestamp formatting (cached by second for high-throughput performance)
            sec = int(record.created)
            if getattr(self, "_last_sec", None) == sec:
                timestamp = self._last_time_str
            elif self.formatter and hasattr(self.formatter, "formatTime"):
                try:
                    timestamp = self.formatter.formatTime(record, getattr(self.formatter, "datefmt", None))
                except Exception:
                    timestamp = datetime.fromtimestamp(sec).strftime("%Y-%m-%d %H:%M:%S")
                self._last_sec = sec
                self._last_time_str = timestamp
            else:
                timestamp = datetime.fromtimestamp(sec).strftime("%Y-%m-%d %H:%M:%S")
                self._last_sec = sec
                self._last_time_str = timestamp

            level = record.levelname or "INFO"

            # Message formatting
            try:
                msg = record.getMessage()
            except Exception:
                msg = str(record.msg)

            # Exception / traceback formatting
            if record.exc_info:
                if not record.exc_text:
                    try:
                        record.exc_text = self.format(record)
                    except Exception:
                        pass
                if record.exc_text and record.exc_text not in msg:
                    msg = f"{msg}\n{record.exc_text}"

            entry = LogEntry(
                timestamp=timestamp,
                level=level,
                message=msg,
                logger_name=record.name,
            )

            with self._lock:
                self._buffer.append(entry)
                active_listeners = list(self._listeners) if self._listeners else None

            # Notify listeners outside the lock
            if active_listeners:
                for listener in active_listeners:
                    try:
                        listener(entry)
                    except Exception:
                        pass

        except Exception:
            self.handleError(record)

    def get_entries(
        self,
        level_filter: Optional[str] = None,
        search_query: Optional[str] = None,
    ) -> List[LogEntry]:
        """
        Retrieve log entries with optional level filtering and case-insensitive keyword search.
        Snapshot isolation ensures iteration safety against concurrent appends.
        """
        with self._lock:
            snapshot = list(self._buffer)

        # 1. Normalize level filter
        normalized_filter: Optional[str] = None
        if level_filter is not None:
            raw_filter = level_filter.strip().upper()
            if raw_filter and raw_filter != "ALL":
                if raw_filter == "WARN":
                    normalized_filter = "WARNING"
                elif raw_filter == "ERR":
                    normalized_filter = "ERROR"
                else:
                    normalized_filter = raw_filter

        # 2. Normalize search query
        normalized_query: Optional[str] = None
        if search_query is not None and search_query.strip():
            normalized_query = search_query.strip().lower()

        # Fast path if no filters active
        if normalized_filter is None and normalized_query is None:
            return snapshot

        results: List[LogEntry] = []
        for entry in snapshot:
            # Check level match
            if normalized_filter is not None:
                if entry.level.upper() != normalized_filter:
                    continue

            # Check search query match (case-insensitive substring across message, level, timestamp, logger)
            if normalized_query is not None:
                msg_match = normalized_query in entry.message.lower()
                lvl_match = normalized_query in entry.level.lower()
                ts_match = normalized_query in entry.timestamp.lower()
                name_match = (
                    entry.logger_name is not None
                    and normalized_query in entry.logger_name.lower()
                )
                if not (msg_match or lvl_match or ts_match or name_match):
                    continue

            results.append(entry)

        return results

    def export_to_file(self, target_path: Union[str, Path]) -> None:
        """
        Atomically export current log buffer snapshot to a destination file.
        Uses temporary file staging and os.replace to guarantee atomic disk writes.
        """
        if not target_path or not str(target_path).strip():
            raise ValueError("Target path must not be empty")

        with self._lock:
            entries = list(self._buffer)

        path = Path(target_path).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)

        content = "".join(f"{e.timestamp} [{e.level}] {e.message}\n" for e in entries)

        temp_path = path.parent / f".{path.name}.{os.getpid()}.{threading.get_ident()}.{uuid.uuid4().hex[:8]}.tmp"
        try:
            with open(temp_path, "w", encoding="utf-8") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())

            if not sys.platform.startswith("win"):
                try:
                    os.chmod(temp_path, 0o600)
                except OSError:
                    pass

            os.replace(temp_path, path)
        except Exception:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass
            raise

    def clear(self) -> None:
        """Clear all buffered log entries."""
        with self._lock:
            self._buffer.clear()

    def add_listener(self, callback: Callable[[LogEntry], None]) -> None:
        """Subscribe a callback to be invoked when new LogEntry arrives."""
        with self._lock:
            if callback not in self._listeners:
                self._listeners.append(callback)

    def remove_listener(self, callback: Callable[[LogEntry], None]) -> None:
        """Unsubscribe a callback."""
        with self._lock:
            if callback in self._listeners:
                self._listeners.remove(callback)

    def __len__(self) -> int:
        with self._lock:
            return len(self._buffer)

    def __bool__(self) -> bool:
        """Ensure GuiLogHandler always evaluates to True in boolean contexts."""
        return True
