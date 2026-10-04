# Project: Obsidian Google Drive Sync Modernization

## Architecture
Obsidian Google Drive Sync is a modern desktop utility orchestrating bidirectional vault synchronization between local Obsidian vaults and Google Drive via `rclone bisync`.

```
+---------------------------------------------------------------------------------------+
|                                     USER INTERFACE                                    |
|  MainWindow (CustomTkinter)                                                           |
|  - Tab 1: Config & Sync (Vaults, Paths, Live Progress Bar, Active File, Status Badges)|
|  - Tab 2: Activity History (Chronological run table, details, transfer metrics)      |
|  - Tab 3: Diagnostics & Logs (Level filtering, search, export, live logging)          |
+---------------------------------------------------------------------------------------+
        ^                                 ^                                 ^
        | Events                          | History queries                 | Log stream
+-------+---------------------------------+---------------------------------+-----------+
|                                  EVENT DISPATCHER                                     |
|  EventDispatcher (src/core/events.py) - Thread-safe Queue & Observer Pub/Sub          |
|  Events: STATUS_CHANGED, PROGRESS_UPDATED, FILE_TRANSFERRED, CONFLICT, BATCH_COMPLETED  |
+---------------------------------------------------------------------------------------+
        ^                                                                   ^
        | Status & Progress events                                          | Notifications
+-------+-----------------------------+                     +---------------+-----------+
|               CORE ENGINE           |                     |        SYSTEM TRAY        |
|  SyncWorker (src/core/sync_worker.py)                     |  TrayManager              |
|  - Streaming subprocess.Popen       |                     |  (src/tray/tray_icon.py)  |
|  - Real-time rclone line parser     |                     |  - Live status summaries  |
|  - Debounced file watcher           |                     |  - 1-click shortcuts      |
|  - SyncHistoryManager persistence   |                     |  - Conflict & batch alerts|
+-------------------------------------+                     +---------------------------+
        |                                                                   |
        v                                                                   v
+-------------------------------------+                     +---------------------------+
|           DATA & LOGGING            |                     |       DESKTOP SYSTEM      |
|  - history.json (Last 100 sync runs)|                     |  - xdg-open / explorer    |
|  - config.json (Multi-vault config) |                     |  - Default web browser    |
|  - sync.log & GuiLogHandler         |                     |  - OS notification daemon |
+-------------------------------------+                     +---------------------------+
```

## Feature Inventory
Every feature identified during the Survey phase mapped to its assigned milestone:

| # | Feature ID | Name | Description | Milestone | Source | Current State |
|---|------------|------|-------------|-----------|--------|---------------|
| 1 | F-01 | Tabbed Navigation | Multi-panel navigation using CTkTabview (Config, History, Diagnostics) | M3 | R1 | Complete |
| 2 | F-02 | Sync Progress Bar | Real-time progress bar reflecting sync progress & percentages | M3 | R1 | Complete |
| 3 | F-03 | Active File Indicator | Real-time visual label displaying current file being transferred | M3 | R1 | Complete |
| 4 | F-04 | Animated/Colored Status | Distinct animated/colored status badges (idle, syncing, success, paused, error) | M3 | R1 | Complete |
| 5 | F-05 | Responsive Layout & Theme | Dynamic layout adapting to window resizing and desktop dark/light theme | M3 | R1 | Complete |
| 6 | F-06 | Responsive UI Threading | Non-blocking background worker execution keeping UI responsive | M1 | R1 | Complete |
| 7 | F-07 | Sync History Persistence | SyncHistoryManager persisting run records to history.json (ring buffer 100) | M2 | R2 | Complete |
| 8 | F-08 | Activity History Panel | Dedicated history table showing at least the last 20 sync operations | M3 | R2 | Complete |
| 9 | F-09 | File Transfer Detail Inspection | Inspection of transferred/modified files per historical sync run | M3 | R2 | Complete |
| 10 | F-10 | Real-Time Log Viewer | In-app live logging viewer connected to Python logger via GuiLogHandler | M2 | R2 | Complete |
| 11 | F-11 | Log Level Filtering | Filter logs by level: ALL, INFO, WARNING, ERROR | M2 | R2 | Complete |
| 12 | F-12 | Log Text Search | Case-insensitive keyword search and match highlighting in logs | M2 | R2 | Complete |
| 13 | F-13 | Log Export Functionality | One-click export of log contents to timestamped .txt/.log file | M2 | R2 | Complete |
| 14 | F-14 | Tray Dynamic Status Summaries | Context menu displaying last sync time, active vault name, and storage quota | M4 | R3 | Complete |
| 15 | F-15 | Tray Sync Now Shortcut | One-click immediate sync trigger from tray menu | M4 | R3 | Complete |
| 16 | F-16 | Tray Pause/Resume Shortcut | One-click sync pause and resume toggle from tray menu | M4 | R3 | Complete |
| 17 | F-17 | Tray Open Local Vault Shortcut | One-click shortcut opening local vault folder via cross-platform launcher | M4 | R3 | Complete |
| 18 | F-18 | Tray Open Google Drive Shortcut | One-click shortcut opening Google Drive web interface in browser | M4 | R3 | Complete |
| 19 | F-19 | Tray Open Activity Logs Shortcut | One-click shortcut bringing up main window to diagnostics tab | M4 | R3 | Complete |
| 20 | F-20 | Tray Conflict Notification | Desktop notification alert on file conflicts during sync | M4 | R3 | Complete |
| 21 | F-21 | Tray Fatal Error Notification | Desktop notification alert on fatal sync failure | M4 | R3 | Complete |
| 22 | F-22 | Tray Batch Complete Notification | Desktop notification on large batch transfer completion (>5 files) | M4 | R3 | Complete |
| 23 | F-23 | Notification Deduplication | Anti-spam deduplication and cooldown mechanism for desktop notifications | M4 | R3 | Complete |
| 24 | F-24 | Streaming Subprocess Output | Popen-based execution parsing rclone stdout lines in real time | M1 | R4 | Complete |
| 25 | F-25 | Decoupled Thread-Safe Events | EventDispatcher pub/sub queue decoupling background threads from UI | M1 | R4 | Complete |
| 26 | F-26 | Graceful Error Boundaries | Exception boundaries preventing thread or notification crashes from killing app | M1 | R4 | Complete |
| 27 | F-27 | Minimized Startup Mode | Clean application startup in normal and --minimized headless mode | M1 | R4 | Complete |
| 28 | F-28 | Comprehensive Modern Test Suite | Full regression test suite + new unit/integration/E2E tests maintaining 95 pass | M5 | R4 | Complete |

## Milestones
 
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | Architecture & Event Core | EventDispatcher, Popen streaming in SyncWorker, error boundaries, typed events | none | DONE |
| M2 | History & Diagnostics Core | SyncHistoryManager, history.json persistence, GuiLogHandler, log filtering/export | M1 | DONE |
| M3 | Modern Responsive GUI | Tabbed CTkTabview layout, dynamic progress bar, active file label, history & log UI | M1, M2 | DONE |
| M4 | System Tray Modernization | Dynamic menu summaries, 1-click shortcuts, conflict/batch notifications | M1, M2 | DONE |
| M5 | Final E2E Pass & Hardening | Pass 100% of E2E test suite (T1-T4) + Tier 5 Adversarial Coverage Hardening | M1, M2, M3, M4 | DONE |

## Interface Contracts

### EventDispatcher Contract (`src/core/events.py`)
```python
from enum import Enum, auto
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional
import time

class EventType(Enum):
    STATUS_CHANGED = auto()       # payload: StatusPayload(status: SyncStatus, message: str)
    PROGRESS_UPDATED = auto()     # payload: ProgressPayload(transferred_bytes: int, total_bytes: int, percentage: float, speed_str: str)
    FILE_TRANSFERRED = auto()     # payload: FilePayload(filename: str, size: int, action: str)
    CONFLICT_DETECTED = auto()    # payload: ConflictPayload(filename: str, details: str)
    BATCH_COMPLETED = auto()      # payload: BatchPayload(total_files: int, total_bytes: int, elapsed_seconds: float)
    LOG_EMITTED = auto()          # payload: LogPayload(level: str, message: str, timestamp: float)

@dataclass
class Event:
    event_type: EventType
    data: Any
    timestamp: float = field(default_factory=time.time)

class EventDispatcher:
    def subscribe(self, event_type: EventType, callback: Callable[[Event], None]) -> None: ...
    def unsubscribe(self, event_type: EventType, callback: Callable[[Event], None]) -> None: ...
    def emit(self, event_type: EventType, data: Any) -> None: ...
```

### SyncHistoryManager Contract (`src/core/history_manager.py`)
```python
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from pathlib import Path

@dataclass
class SyncRunRecord:
    id: str
    timestamp: str             # ISO 8601 string
    vault_name: str
    status: str                # SUCCESS, ERROR, CONFLICT, PARTIAL
    duration_seconds: float
    files_transferred: List[str] = field(default_factory=list)
    error_message: Optional[str] = None
    bytes_transferred: int = 0

class SyncHistoryManager:
    def __init__(self, history_file: Optional[Path] = None, max_records: int = 100): ...
    def record_run(self, record: SyncRunRecord) -> None: ...
    def get_recent_runs(self, limit: int = 20) -> List[SyncRunRecord]: ...
    def clear_history(self) -> None: ...
```

### GuiLogHandler Contract (`src/utils/log_handler.py`)
```python
import logging
from dataclasses import dataclass
from typing import List, Optional

@dataclass
class LogEntry:
    timestamp: str
    level: str
    message: str

class GuiLogHandler(logging.Handler):
    def __init__(self, max_entries: int = 1000): ...
    def emit(self, record: logging.LogRecord) -> None: ...
    def get_entries(self, level_filter: Optional[str] = None, search_query: Optional[str] = None) -> List[LogEntry]: ...
    def export_to_file(self, target_path: str) -> None: ...
```

## Code Layout
- `src/core/events.py` — EventDispatcher pub/sub event system (Owned by M1)
- `src/core/sync_worker.py` — SyncWorker subprocess streaming & event emission (Owned by M1)
- `src/core/history_manager.py` — SyncHistoryManager and data persistence (Owned by M2)
- `src/utils/log_handler.py` — GuiLogHandler and log filtering/export (Owned by M2)
- `src/utils/logger.py` — Application logging configuration (Owned by M2)
- `src/gui/app_window.py` — Tabbed navigation, progress bars, history & log panels (Owned by M3)
- `src/tray/tray_icon.py` — Dynamic summaries, shortcuts, enhanced notifications (Owned by M4)
- `src/main.py` — Application entry point, wiring event bus, tray, and GUI (Owned by M1/M4)
- `tests/` — Unit and integration tests (Owned by corresponding milestone workers)
- `tests/e2e/` — Requirement-driven opaque-box E2E tests (Owned by E2E Testing Track)
