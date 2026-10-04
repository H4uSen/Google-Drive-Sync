"""
SyncHistoryManager and SyncRunRecord persistence engine for Obsidian Google Drive Sync.
Adheres to the SyncHistoryManager Contract defined in PROJECT.md (Feature F-07).
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional, Union
from pathlib import Path
from datetime import datetime, timezone
import json
import os
import sys
import shutil
import logging
import threading
import uuid

from src.utils.paths import get_history_file_path

logger = logging.getLogger(__name__)


@dataclass
class SyncRunRecord:
    id: str
    timestamp: str             # ISO 8601 string, e.g. "2026-10-03T14:32:10Z"
    vault_name: str
    status: str                # SUCCESS, ERROR, CONFLICT, PARTIAL
    duration_seconds: float
    files_transferred: List[str] = field(default_factory=list)
    error_message: Optional[str] = None
    bytes_transferred: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> SyncRunRecord:
        allowed = set(cls.__dataclass_fields__.keys())
        clean_kwargs: Dict[str, Any] = {k: v for k, v in data.items() if k in allowed}

        if "duration_seconds" in clean_kwargs:
            try:
                clean_kwargs["duration_seconds"] = float(clean_kwargs["duration_seconds"])
            except (ValueError, TypeError):
                clean_kwargs["duration_seconds"] = 0.0

        if "bytes_transferred" in clean_kwargs:
            try:
                clean_kwargs["bytes_transferred"] = int(clean_kwargs["bytes_transferred"])
            except (ValueError, TypeError):
                clean_kwargs["bytes_transferred"] = 0

        if "files_transferred" in clean_kwargs:
            if isinstance(clean_kwargs["files_transferred"], (list, tuple)):
                clean_kwargs["files_transferred"] = [str(f) for f in clean_kwargs["files_transferred"]]
            else:
                clean_kwargs["files_transferred"] = []

        if "status" in clean_kwargs and isinstance(clean_kwargs["status"], str):
            clean_kwargs["status"] = clean_kwargs["status"].upper()

        return cls(**clean_kwargs)


class SyncHistoryManager:
    """
    Thread-safe synchronization history persistence engine with ring-buffer retention,
    atomic file writes, and resilient recovery from corrupted JSON files.
    """

    def __init__(
        self,
        history_file: Optional[Union[Path, str]] = None,
        max_records: int = 100,
    ) -> None:
        if history_file is None:
            self.history_file = get_history_file_path()
        else:
            self.history_file = Path(history_file)

        self.max_records = max(1, int(max_records))
        self._lock = threading.RLock()
        self._records: List[SyncRunRecord] = []
        self._load()

    def record_run(self, record: SyncRunRecord) -> None:
        """
        Record a synchronization execution. Prepends record to in-memory list,
        prunes oldest records beyond max_records, and atomically persists to disk.
        """
        if not isinstance(record, SyncRunRecord):
            raise TypeError(f"Expected SyncRunRecord, got {type(record).__name__}")

        with self._lock:
            # Reverse chronological: newest record is prepended at index 0
            self._records.insert(0, record)
            if len(self._records) > self.max_records:
                self._records = self._records[:self.max_records]
            self._save()

    def get_recent_runs(self, limit: int = 20) -> List[SyncRunRecord]:
        """
        Retrieve recent synchronization records in reverse-chronological order (newest first).
        """
        with self._lock:
            effective_limit = max(0, int(limit))
            return list(self._records[:effective_limit])

    def clear_history(self) -> None:
        """
        Clear all synchronization history in memory and persist empty history to disk.
        """
        with self._lock:
            self._records.clear()
            self._save()

    def get_run_by_id(self, run_id: str) -> Optional[SyncRunRecord]:
        """Lookup a specific run record by unique ID."""
        with self._lock:
            for r in self._records:
                if r.id == run_id:
                    return r
            return None

    def __len__(self) -> int:
        with self._lock:
            return len(self._records)

    def __bool__(self) -> bool:
        """Ensure SyncHistoryManager always evaluates to True in boolean contexts."""
        return True

    def _load(self) -> None:
        """
        Load records from disk with automatic recovery from missing or corrupted JSON files.
        """
        if not self.history_file.exists():
            self._records = []
            return

        try:
            content = self.history_file.read_text(encoding="utf-8").strip()
            if not content:
                self._records = []
                return

            data = json.loads(content)
            if not isinstance(data, list):
                logger.warning(
                    f"History file {self.history_file} root is not a list ({type(data).__name__}). Backing up and resetting."
                )
                self._create_corrupted_backup()
                self._records = []
                return

            records: List[SyncRunRecord] = []
            for item in data:
                if isinstance(item, dict):
                    try:
                        record = SyncRunRecord.from_dict(item)
                        records.append(record)
                    except Exception as parse_err:
                        logger.warning(f"Skipping malformed history record: {parse_err}")
                else:
                    logger.warning(f"Skipping non-dict entry in history: {item}")

            self._records = records[:self.max_records]

        except Exception as ex:
            logger.error(f"Error loading sync history from {self.history_file}: {ex}. Backing up and resetting.")
            self._create_corrupted_backup()
            self._records = []

    def _save(self) -> None:
        """
        Atomically persist records to history.json via temporary file replacement.
        """
        records_payload = [r.to_dict() for r in self._records]
        parent_dir = self.history_file.parent
        parent_dir.mkdir(parents=True, exist_ok=True, mode=0o700)

        temp_file = parent_dir / f".{self.history_file.name}.{os.getpid()}.{threading.get_ident()}.{uuid.uuid4().hex[:8]}.tmp"
        try:
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(records_payload, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())

            if not sys.platform.startswith("win"):
                try:
                    os.chmod(temp_file, 0o600)
                except OSError:
                    pass

            temp_file.replace(self.history_file)
        except Exception as save_err:
            logger.error(f"Failed to atomically persist sync history to {self.history_file}: {save_err}")
            if temp_file.exists():
                try:
                    temp_file.unlink()
                except OSError:
                    pass
            raise

    def _create_corrupted_backup(self) -> None:
        """Create a forensic backup copy of corrupted history file."""
        try:
            bak_path = self.history_file.with_suffix(".json.bak")
            shutil.copyfile(self.history_file, bak_path)
            logger.info(f"Preserved corrupted history file to {bak_path}")
        except Exception as bak_err:
            logger.warning(f"Failed to create history backup: {bak_err}")
