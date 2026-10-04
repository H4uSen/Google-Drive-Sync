"""
Core event messaging system providing a thread-safe, decoupled pub/sub architecture.
Adheres to the EventDispatcher Contract defined in PROJECT.md.
"""
from __future__ import annotations
from enum import Enum, auto
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING
import time
import logging
import threading

if TYPE_CHECKING:
    from src.core.sync_worker import SyncStatus

logger = logging.getLogger(__name__)


class EventType(Enum):
    STATUS_CHANGED = auto()       # payload: StatusPayload(status: SyncStatus, message: str)
    PROGRESS_UPDATED = auto()     # payload: ProgressPayload(...)
    FILE_TRANSFERRED = auto()     # payload: FilePayload(...)
    CONFLICT_DETECTED = auto()    # payload: ConflictPayload(...)
    BATCH_COMPLETED = auto()      # payload: BatchPayload(...)
    LOG_EMITTED = auto()          # payload: LogPayload(...)


@dataclass
class StatusPayload:
    status: Any                   # SyncStatus instance or string
    message: str
    vault_name: Optional[str] = None


@dataclass
class ProgressPayload:
    transferred_bytes: int = 0
    total_bytes: int = 0
    percentage: float = 0.0       # 0.0 to 100.0
    speed_str: str = ""           # e.g. "1.2 MB/s"
    current_file: Optional[str] = None
    eta_str: Optional[str] = None


@dataclass
class FilePayload:
    filename: str
    size: int = 0
    action: str = "transferred"   # e.g. "Copied (new)", "Deleted", "transferred"
    vault_name: Optional[str] = None


@dataclass
class ConflictPayload:
    filename: str
    details: str = ""
    local_path: Optional[str] = None
    remote_path: Optional[str] = None


@dataclass
class BatchPayload:
    total_files: int = 0
    total_bytes: int = 0
    elapsed_seconds: float = 0.0
    files: List[str] = field(default_factory=list)
    status: str = "SUCCESS"


@dataclass
class LogPayload:
    level: str
    message: str
    timestamp: float = field(default_factory=time.time)
    logger_name: Optional[str] = None


@dataclass
class Event:
    event_type: EventType
    data: Any
    timestamp: float = field(default_factory=time.time)


class EventDispatcher:
    """
    Thread-safe publisher/subscriber event dispatcher with listener error isolation.
    """
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._subscribers: Dict[EventType, List[Callable[[Event], None]]] = {}
        self._wildcard_subscribers: List[Callable[[Event], None]] = []

    def subscribe(self, event_type: EventType, callback: Callable[[Event], None]) -> None:
        """Subscribe a callback to a specific EventType. Idempotent."""
        if not callable(callback):
            raise TypeError("Subscriber callback must be callable")
        with self._lock:
            if event_type not in self._subscribers:
                self._subscribers[event_type] = []
            if callback not in self._subscribers[event_type]:
                self._subscribers[event_type].append(callback)

    def subscribe_all(self, callback: Callable[[Event], None]) -> None:
        """Subscribe a callback to all events (wildcard)."""
        if not callable(callback):
            raise TypeError("Subscriber callback must be callable")
        with self._lock:
            if callback not in self._wildcard_subscribers:
                self._wildcard_subscribers.append(callback)

    def unsubscribe(self, event_type: EventType, callback: Callable[[Event], None]) -> None:
        """Unsubscribe a callback from an EventType. Safe no-op if not present."""
        with self._lock:
            if event_type in self._subscribers:
                try:
                    self._subscribers[event_type].remove(callback)
                except ValueError:
                    pass
                if not self._subscribers[event_type]:
                    del self._subscribers[event_type]

    def unsubscribe_all(self, callback: Callable[[Event], None]) -> None:
        """Unsubscribe a callback from wildcard subscriptions and all event types."""
        with self._lock:
            if callback in self._wildcard_subscribers:
                try:
                    self._wildcard_subscribers.remove(callback)
                except ValueError:
                    pass
            for event_type in list(self._subscribers.keys()):
                self.unsubscribe(event_type, callback)

    def emit(self, event_type: EventType, data: Any = None) -> None:
        """
        Emit an event to all registered subscribers.
        Creates an Event envelope with timestamp, captures subscriber snapshot under lock,
        and invokes callbacks outside lock with individual error isolation boundaries.
        """
        if isinstance(data, Event):
            event = data
        else:
            event = Event(event_type=event_type, data=data)

        with self._lock:
            callbacks = list(self._subscribers.get(event_type, []))
            wildcards = list(self._wildcard_subscribers)

        for cb in callbacks + wildcards:
            try:
                cb(event)
            except Exception as ex:
                cb_name = getattr(cb, "__name__", repr(cb))
                logger.exception(
                    "Listener exception in callback %s on event %s: %s",
                    cb_name, event_type.name, ex
                )

    def clear(self) -> None:
        """Remove all subscribers."""
        with self._lock:
            self._subscribers.clear()
            self._wildcard_subscribers.clear()

    def subscriber_count(self, event_type: Optional[EventType] = None) -> int:
        """Return subscriber count for a type, or total across all types."""
        with self._lock:
            if event_type is not None:
                return len(self._subscribers.get(event_type, []))
            return sum(len(cbs) for cbs in self._subscribers.values()) + len(self._wildcard_subscribers)


_default_dispatcher: Optional[EventDispatcher] = None
_dispatcher_lock = threading.Lock()


def get_dispatcher() -> EventDispatcher:
    """Return the global default EventDispatcher instance."""
    global _default_dispatcher
    if _default_dispatcher is None:
        with _dispatcher_lock:
            if _default_dispatcher is None:
                _default_dispatcher = EventDispatcher()
    return _default_dispatcher


def reset_dispatcher() -> None:
    """Reset and clear the global default EventDispatcher instance."""
    global _default_dispatcher
    with _dispatcher_lock:
        if _default_dispatcher is not None:
            _default_dispatcher.clear()
            _default_dispatcher = None
