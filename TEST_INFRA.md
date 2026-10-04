# TEST_INFRA — End-to-End Test Infrastructure Specification

**Project**: Obsidian Google Drive Sync Desktop Modernization  
**Component**: Requirement-Driven Opaque-Box E2E Test Suite  
**Author**: `e2e_test_writer_1`  
**Date**: 2026-10-03  
**Status**: ACTIVE / OPERATIONAL  

---

## 1. Testing Philosophy & Architecture

### 1.1 Opaque-Box Requirement-Driven Testing
The end-to-end test suite validates the system exclusively through its **public contracts, observable outputs, filesystem artifacts, CLI behavior, and event streams**. Tests treat internal implementation details as an opaque box:
- **No private state hacking**: Tests verify observable side effects (e.g., records in `history.json`, log entries from `GuiLogHandler`, dispatched events on `EventDispatcher`, status badges, tray menu actions, and subprocess calls).
- **Contract-first verification**: Tests adhere strictly to the formal interface contracts defined in `PROJECT.md` (`EventDispatcher`, `SyncHistoryManager`, `GuiLogHandler`, `SyncWorker`, `TrayManager`, `MainWindow`).
- **Deterministic and reproducible**: Every test establishes an explicit authoritative baseline for expected behavior derived from `ORIGINAL_REQUEST.md` and `PROJECT.md`.

### 1.2 Execution Isolation & Sandboxing
All tests run with 100% isolation to ensure they never contaminate the host system or depend on test execution order:
1. **Filesystem Sandboxing**: All configuration and data files (`config.json`, `history.json`, `sync.log`, `app.lock`) are confined to an isolated temporary directory via overridden `XDG_CONFIG_HOME` and patched `get_app_dir()`. The host's `~/.config/obsidian-gdrive-sync` is never read or modified.
2. **Subprocess Isolation**: External invocations of `rclone` are controlled via a synthetic streaming harness (`mock_rclone`) capable of generating realistic stdout streams, simulate bandwidth throttling, progress milestones, bisync conflicts, and exit codes.
3. **Desktop & Display Safety**: GUI components are executed safely in headless CI/server environments without requiring an active X11 or Wayland display server (`headless_gui` fixture with mock Tk loops).
4. **Desktop Environment Mocks**: External OS calls (`xdg-open`, `webbrowser.open`, system notification daemons) are captured and verified without launching external desktop processes.

### 1.3 Progressive Milestone Verification & Strict M5 Mode
To accommodate parallel development across milestones (M1 Architecture & Events, M2 History & Diagnostics, M3 GUI Modernization, M4 Tray Integration, M5 Hardening):
- **Progressive Mode (Default)**: Tests automatically probe feature availability. Implemented features execute real logic and assert contract requirements. Features whose underlying modules or capabilities are scheduled for future milestones report informative skips (`SKIPPED [F-XX pending in M-X]`). The entire test suite collects cleanly and passes with exit code 0 at any milestone stage.
- **Strict Mode (`E2E_STRICT=1`)**: Enforces that 100% of all 28 features (F-01 through F-28) across all 4 tiers must be implemented, operational, and passing without any skips. This mode is the gate requirement for Milestone 5.

---

## 2. 4-Tier Test Architecture Specification

The test suite is structured into four distinct hierarchical tiers:

```
+-----------------------------------------------------------------------------------+
|                        TIER 4: REAL-WORLD APPLICATION SCENARIOS                   |
|  Realistic end-to-end user workflows: Onboarding, Daily Notes, Multi-Vault, etc.   |
+-----------------------------------------------------------------------------------+
                                         ^
+-----------------------------------------------------------------------------------+
|                     TIER 3: CROSS-FEATURE COMBINATION SUITE                       |
|  Pairwise and multi-component interactions: Sync + History + Tray + Logs + Events |
+-----------------------------------------------------------------------------------+
                                         ^
+-----------------------------------------------------------------------------------+
|                    TIER 2: BOUNDARY & CORNER CASE HARDENING                       |
|  Edge conditions: Root path protection, locks, quota limits, error recovery, etc. |
+-----------------------------------------------------------------------------------+
                                         ^
+-----------------------------------------------------------------------------------+
|                      TIER 1: FEATURE ISOLATION COVERAGE                           |
|  Direct, independent verification of each of the 28 features (F-01 through F-28) |
+-----------------------------------------------------------------------------------+
```

### 2.1 Tier 1: Feature Coverage (Isolation)
Exercises every cataloged feature in isolation against its defined contract and acceptance criteria:
- **F-01**: Multi-Panel Tab Navigation (`CTkTabview` switching between Config, History, Diagnostics).
- **F-02**: Dynamic Sync Progress Bar (real-time progress bar reflecting sync percentage).
- **F-03**: Active File Transfer Indicator (live label displaying active file being transferred).
- **F-04**: Animated/Colored Status Badges (distinct visual badges for IDLE, SYNCING, SUCCESS, PAUSED, ERROR).
- **F-05**: Responsive Layout & Desktop Theme (dynamic layout adaptation, dark/light theme support).
- **F-06**: Responsive UI Threading (non-blocking background worker execution keeping UI responsive).
- **F-07**: Sync History Persistence Engine (`SyncHistoryManager` saving to `history.json` with ring buffer 100).
- **F-08**: Activity History Panel UI (dedicated history view displaying at least recent 20 runs).
- **F-09**: Detailed File Transfer Inspection (inspectable file transfer details per historical sync run).
- **F-10**: In-App Real-Time Log Viewer (`GuiLogHandler` streaming Python logs into UI buffer).
- **F-11**: Log Level Filtering (filtering log entries by INFO, WARNING, ERROR, ALL).
- **F-12**: Log Text Search (case-insensitive keyword search and match highlighting).
- **F-13**: Log Export Functionality (one-click log export to timestamped text/log file).
- **F-14**: Dynamic Tray Status Summaries (context menu displaying status, active vault, last sync, quota).
- **F-15**: Tray Shortcut: Trigger Sync Now (one-click immediate sync trigger from tray).
- **F-16**: Tray Shortcut: Pause / Resume Sync (one-click toggle for worker pause state).
- **F-17**: Tray Shortcut: Open Local Vault Folder (cross-platform folder launcher via `xdg-open`).
- **F-18**: Tray Shortcut: Open Google Drive Web (one-click web browser launcher for Google Drive).
- **F-19**: Tray Shortcut: Open Activity Logs (focuses main window and activates diagnostics tab).
- **F-20**: Tray Conflict Notification (desktop notification alert on bisync file conflicts).
- **F-21**: Tray Fatal Error Notification (desktop notification on fatal sync failures).
- **F-22**: Tray Batch Complete Notification (desktop notification on large batch transfers >5 files).
- **F-23**: Notification Deduplication (15-minute cooldown and error suppression mechanism).
- **F-24**: Real-Time Rclone Stream Parser (`subprocess.Popen` line parser extracting transfer stats).
- **F-25**: Decoupled Thread-Safe Event Bus (`EventDispatcher` pub/sub queue decoupling worker and UI).
- **F-26**: Graceful Error Boundaries (thread exception boundaries preventing background service termination).
- **F-27**: Minimized Startup Mode (`--minimized` headless launch keeping window hidden and tray active).
- **F-28**: Comprehensive Modern Test Suite (integration with existing 95 tests and full test runner).

### 2.2 Tier 2: Boundary & Corner Cases
Stresses the system under boundary values, exceptional conditions, and hostile environments:
- **E-01**: Root & Anchor Path Safety (rejects `/`, `~`, `C:\` as vault paths to prevent filesystem destruction).
- **E-02**: Missing Vault Directory (handles deleted local vault gracefully without running destructive bisync).
- **E-03**: Stale Lock File Recovery (cleans up orphan `.lck` from dead PIDs, preserves live instance locks).
- **E-04**: Bisync Massive Deletion Safety Trip (strictly forbids automated `--resync` on safety trips).
- **E-05**: Mid-Sync Network Outage / Process Timeout (worker stays alive, marks error, triggers notification cooldown).
- **E-06**: Google Drive Storage Quota Limits (handles quota exhaustion >90% and 100% with visual alerts).
- **E-07**: Large Batch Transfer Boundaries (smooth handling of >100 files without UI freezing).
- **E-08**: Rapid File System Edit Bursts (elastic debounce timer coalescing saves within 500ms).
- **E-09**: Concurrent Manual Sync Invocations (rapid duplicate clicks ignored safely without overlapping runs).
- **E-10**: Headless / Missing DISPLAY Environment (clean operation without X11 server).
- **E-11**: Missing Desktop Utilities (graceful fallback if `xdg-open` or notification daemon is absent).
- **E-12**: High-Volume Log Flooding (handles bursts of 5,000 log lines with bounded memory ring buffer).
- **E-13**: Corrupted `history.json` Recovery (auto-recovers from invalid JSON without crashing application).
- **E-14**: Vault Profile Switch in Flight (safe transition or queuing when switching vaults while syncing).

### 2.3 Tier 3: Cross-Feature Combinations
Validates emergent behavior across multiple interacting subsystems:
- **C-01**: Full Sync Lifecycle (Worker streaming -> EventDispatcher -> History persistence -> Log handler).
- **C-02**: Conflict Detection Pipeline (Rclone conflict line -> Event bus -> Tray notification -> History record).
- **C-03**: Large Batch Notification Pipeline (Worker >5 files -> Progress stream -> Batch event -> Notification -> History).
- **C-04**: Tray-to-UI Synchronization (Tray "Sync Now" -> Worker execution -> Tray menu update -> GUI badge update).
- **C-05**: Tray Pause & File Watcher Coordination (Tray pause -> Watcher edits queued -> Tray resume -> Sync fires).
- **C-06**: Subprocess Failure Cascading (Process crash -> Error boundary catches -> Log captured -> Cooldown notification).
- **C-07**: Concurrent Log Streaming & Export (Log export executed during heavy active logging without locking or data corruption).

### 2.4 Tier 4: Real-World Application Scenarios
Simulates realistic, multi-step end-to-end user journeys:
- **S-01**: First-Run & Onboarding Workflow (Unconfigured launch -> notification -> vault config -> initial sync -> history recorded).
- **S-02**: Headless Background Daemon Workflow (`--minimized` startup -> background watcher -> note edit -> sync -> tray summary update).
- **S-03**: Heavy Daily Note Workflow (Continuous typing -> debounced syncs -> live progress -> active file labels -> log inspection).
- **S-04**: Offline-to-Online Recovery Workflow (Network disconnects -> error boundary & cooldown -> network restores -> manual sync succeeds).
- **S-05**: Multi-Vault Management Workflow (Switching between Vault A and Vault B -> watcher rebinding -> isolated history records).

---

## 3. Complete Feature Coverage Mapping (F-01 through F-28)

| Feature ID | Feature Name | Milestone | Tier 1 (Isolation) | Tier 2 (Boundary) | Tier 3 (Combination) | Tier 4 (Scenario) |
|---|---|---|---|---|---|---|
| **F-01** | Multi-Panel Tab Navigation | M3 | `test_f01_tabbed_navigation` | `test_e10_headless_display` | `test_c04_tray_to_ui_sync` | `S-01`, `S-03` |
| **F-02** | Dynamic Sync Progress Bar | M3 | `test_f02_sync_progress_bar` | `test_e07_large_batch_boundary` | `test_c01_full_sync_lifecycle`, `test_c03` | `S-03` |
| **F-03** | Active File Indicator | M3 | `test_f03_active_file_indicator` | `test_e08_rapid_edit_burst` | `test_c01_full_sync_lifecycle` | `S-03` |
| **F-04** | Animated/Colored Status Badges | M3 | `test_f04_status_badges` | `test_e05_network_outage_error` | `test_c04_tray_to_ui_sync` | `S-01`, `S-04` |
| **F-05** | Responsive Layout & Theme | M3 | `test_f05_responsive_layout_theme` | `test_e10_headless_display` | — | `S-01` |
| **F-06** | Responsive UI Threading | M1 | `test_f06_responsive_ui_threading` | `test_e09_concurrent_manual_sync` | `test_c01_full_sync_lifecycle` | `S-02`, `S-03` |
| **F-07** | Sync History Persistence Engine | M2 | `test_f07_history_persistence` | `test_e13_corrupt_history_recovery` | `test_c01`, `test_c02`, `test_c03` | `S-01`, `S-03`, `S-05` |
| **F-08** | Activity History Panel UI | M3 | `test_f08_history_panel_ui` | `test_e13_corrupt_history_recovery` | `test_c01_full_sync_lifecycle` | `S-03`, `S-05` |
| **F-09** | Detailed File Transfer Inspection | M3 | `test_f09_file_detail_inspection` | `test_e07_large_batch_boundary` | `test_c01`, `test_c03` | `S-03` |
| **F-10** | In-App Real-Time Log Viewer | M2 | `test_f10_realtime_log_viewer` | `test_e12_high_volume_log_flood` | `test_c01_full_sync_lifecycle` | `S-03`, `S-04` |
| **F-11** | Log Level Filtering | M2 | `test_f11_log_level_filtering` | `test_e12_high_volume_log_flood` | `test_c06_subprocess_failure` | `S-03` |
| **F-12** | Log Text Search | M2 | `test_f12_log_text_search` | `test_e12_high_volume_log_flood` | — | `S-03` |
| **F-13** | Log Export Functionality | M2 | `test_f13_log_export` | `test_e11_missing_desktop_tools` | `test_c07_concurrent_log_export` | `S-03` |
| **F-14** | Dynamic Tray Status Summaries | M4 | `test_f14_tray_status_summaries` | `test_e06_quota_limits` | `test_c04_tray_to_ui_sync` | `S-02`, `S-05` |
| **F-15** | Tray Shortcut: Trigger Sync Now | M4 | `test_f15_tray_sync_now` | `test_e09_concurrent_manual_sync` | `test_c04_tray_to_ui_sync` | `S-04` |
| **F-16** | Tray Shortcut: Pause / Resume Sync | M4 | `test_f16_tray_pause_resume` | `test_e08_rapid_edit_burst` | `test_c05_tray_pause_watcher` | `S-02` |
| **F-17** | Tray Shortcut: Open Local Vault | M4 | `test_f17_tray_open_vault` | `test_e11_missing_desktop_tools` | — | `S-02` |
| **F-18** | Tray Shortcut: Open Google Drive | M4 | `test_f18_tray_open_gdrive` | `test_e11_missing_desktop_tools` | — | `S-02` |
| **F-19** | Tray Shortcut: Open Activity Logs | M4 | `test_f19_tray_open_logs` | `test_e11_missing_desktop_tools` | `test_c04_tray_to_ui_sync` | `S-02` |
| **F-20** | Tray Conflict Notification | M4 | `test_f20_tray_conflict_alert` | `test_e04_bisync_safety_trip` | `test_c02_conflict_pipeline` | `S-04` |
| **F-21** | Tray Fatal Error Notification | M4 | `test_f21_tray_fatal_error_alert` | `test_e05_network_outage_error` | `test_c06_subprocess_failure` | `S-04` |
| **F-22** | Tray Batch Complete Notification | M4 | `test_f22_tray_batch_notification`| `test_e07_large_batch_boundary` | `test_c03_batch_pipeline` | `S-03` |
| **F-23** | Notification Deduplication | M4 | `test_f23_notification_deduplication`| `test_e05_network_outage_error`| `test_c06_subprocess_failure` | `S-04` |
| **F-24** | Real-Time Rclone Stream Parser | M1 | `test_f24_streaming_subprocess` | `test_e05_network_outage_error` | `test_c01_full_sync_lifecycle` | `S-03` |
| **F-25** | Decoupled Thread-Safe Event Bus | M1 | `test_f25_decoupled_events` | `test_e09_concurrent_manual_sync` | `test_c01`, `test_c02`, `test_c03` | `S-01` through `S-05` |
| **F-26** | Graceful Error Boundaries | M1 | `test_f26_error_boundaries` | `test_e02`, `test_e03`, `test_e05` | `test_c06_subprocess_failure` | `S-04` |
| **F-27** | Minimized Startup Mode | M1 | `test_f27_minimized_startup` | `test_e10_headless_display` | `test_c05_tray_pause_watcher` | `S-02` |
| **F-28** | Regression & Modern Test Suite | M5 | `test_f28_test_suite_integrity` | All Tier 2 | All Tier 3 | All Tier 4 |

---

## 4. Test File Layout & Organization

All E2E test suites reside in `tests/e2e/`:

```
tests/e2e/
├── __init__.py                  # Package marker
├── conftest.py                  # Isolated sandboxing fixtures, mock rclone, headless GUI, feature probes
├── test_tier1_features.py       # 28 isolation tests for F-01 through F-28
├── test_tier2_boundaries.py     # 14 boundary & corner tests (E-01 through E-14)
├── test_tier3_combinations.py   # 7 cross-feature integration tests (C-01 through C-07)
├── test_tier4_scenarios.py      # 5 realistic user workflow tests (S-01 through S-05)
└── run_e2e.py                   # Dedicated CLI runner with formatted tier reports and coverage stats
```

---

## 5. Execution Guide

### 5.1 Standard Verification (Pytest)
Run the full E2E suite via the virtualenv's pytest binary:
```bash
.venv/bin/pytest tests/e2e/
```

To run with verbose output showing exact test names and skip reasons:
```bash
.venv/bin/pytest -v tests/e2e/
```

### 5.2 Strict Mode Verification (Milestone 5 Gate)
Run the suite with strict enforcement (zero skips allowed; all 28 features must be active and passing):
```bash
E2E_STRICT=1 .venv/bin/pytest tests/e2e/
```

### 5.3 Dedicated E2E Runner
Run the dedicated runner script to inspect per-tier metrics and feature status:
```bash
.venv/bin/python tests/e2e/run_e2e.py
```

Options:
- `--strict`: Equivalent to `E2E_STRICT=1`.
- `--tier [1|2|3|4]`: Run only tests belonging to a specific tier.
- `--verbose`: Show full traceback and execution timings.

### 5.4 Full Regression Baseline
Verify that both the existing 95 unit tests and the E2E suite run cleanly together without any regressions:
```bash
.venv/bin/pytest tests/
```

---

## 6. Expected Output Derivation & Authoritative Baselines

| Test Category | Authoritative Baseline Source | Verification Assertion |
|---|---|---|
| **Event Dispatching** | `PROJECT.md § EventDispatcher Contract` | Events emitted with correct `EventType`, timestamp, and payload dataclasses. |
| **History Persistence** | `PROJECT.md § SyncHistoryManager Contract` | Valid `history.json` created in isolated config dir, entries conform to `SyncRunRecord`, ring buffer capped at 100. |
| **Log Management** | `PROJECT.md § GuiLogHandler Contract` | `LogEntry` records captured, filtered by level (`INFO`, `WARNING`, `ERROR`), and exported with byte fidelity. |
| **Tray Quick Controls** | `ORIGINAL_REQUEST.md § R3` & `PROJECT.md § F-14..F-19` | Context menu exposes dynamic summaries; 1-click callbacks trigger expected worker/OS actions. |
| **Notifications** | `ORIGINAL_REQUEST.md § R3` & `PROJECT.md § F-20..F-23` | Notification dispatched with expected severity, title, message; deduplication window active (15m). |
| **Safety Boundaries** | `spec_analysis.md § 6 (E-01..E-14)` | Invalid paths rejected; dead lock PIDs recovered; bisync fatal trips never auto-resync; daemons survive worker errors. |
| **CLI Startup** | `src.main` & `ORIGINAL_REQUEST.md § Acceptance Criteria` | Normal startup loads GUI; `--minimized` hides window and auto-starts sync if vault configured. |
