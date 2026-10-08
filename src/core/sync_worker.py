from __future__ import annotations
from enum import Enum
from pathlib import Path
import os
import json
import re
import threading
import time
import logging
import uuid
from datetime import datetime
from typing import Callable, Optional, List

from src.core.config import ConfigData
from src.core.rclone_manager import RcloneManager
from src.utils.paths import get_filters_file_path
from src.core.sync_run import (
    ANSI_ESCAPE_RE,
    Launcher,
    SyncRequest,
    SyncRun,
    SyncRunResult,
    popen_launcher,
)
from src.core.vault_watcher import VaultWatcher
from src.core.history_manager import SyncHistoryManager, SyncRunRecord
from src.core.events import (
    EventDispatcher,
    EventType,
    StatusPayload,
    BatchPayload,
)

logger = logging.getLogger(__name__)

class SyncStatus(Enum):
    IDLE = "idle"
    SYNCING = "syncing"
    SUCCESS = "success"
    PAUSED = "paused"
    ERROR = "error"

    @property
    def color(self) -> str:
        return COLOR_MAP[self]


COLOR_MAP = {
    SyncStatus.IDLE: "#4CAF50",
    SyncStatus.SUCCESS: "#4CAF50",
    SyncStatus.SYNCING: "#2196F3",
    SyncStatus.PAUSED: "#FFC107",
    SyncStatus.ERROR: "#F44336",
}


def clean_error_message(err_msg: str) -> str:
    cleaned = ANSI_ESCAPE_RE.sub("", err_msg)
    lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
    error_lines = [l for l in lines if "ERROR" in l or "Fatal" in l]
    if error_lines:
        last = error_lines[-1]
        if "ERROR :" in last:
            return last.split("ERROR :", 1)[1].strip()
        return last
    non_notices = [l for l in lines if not l.startswith("NOTICE:")]
    if non_notices:
        return non_notices[-1]
    return lines[-1] if lines else "Error en proceso rclone"


def try_recover_stale_lock(err_text: str) -> bool:
    """
    Checks if the error was caused by a stale rclone bisync lock file from a dead process.
    If so, safely removes the lock file and returns True so the caller can retry.
    """
    clean_text = ANSI_ESCAPE_RE.sub("", err_text)
    match = re.search(r'([^\s"\'\(\)]+\.lck)', clean_text)
    if not match:
        return False

    lock_file = Path(match.group(1))
    if not lock_file.is_file():
        return False

    try:
        if lock_file.stat().st_size == 0:
            logger.info(f"Lock file vacío detectado. Eliminando {lock_file}...")
            lock_file.unlink(missing_ok=True)
            return True

        content = lock_file.read_text(encoding="utf-8").strip()
        data = json.loads(content)
        pid_str = data.get("PID")
        if not pid_str:
            return False
        pid = int(pid_str)
        try:
            os.kill(pid, 0)
            logger.warning(f"Lock rclone activo pertenece al proceso en ejecución PID {pid}. No se eliminará.")
            return False
        except ProcessLookupError:
            logger.info(f"Lock huérfano detectado de proceso muerto PID {pid}. Eliminando {lock_file}...")
            lock_file.unlink(missing_ok=True)
            return True
        except PermissionError:
            logger.warning(f"Proceso PID {pid} existe pero no se tienen permisos. Lock no eliminado.")
            return False
    except Exception as ex:
        logger.error(f"Error analizando lock file {lock_file}: {ex}")
        return False


class SyncWorker:
    def __init__(
        self,
        config: ConfigData,
        rclone_manager: RcloneManager,
        event_dispatcher: Optional[EventDispatcher] = None,
        history_manager: Optional[SyncHistoryManager] = None,
        launcher: Launcher = popen_launcher,
        filters_file: Optional[Path] = None,
    ):
        self.config = config
        self.rclone = rclone_manager
        self.dispatcher = event_dispatcher if event_dispatcher is not None else EventDispatcher()
        self.history_manager = history_manager
        self._launcher = launcher
        self._filters_file = filters_file
        self.run_timeout: float = 900
        self.status = SyncStatus.IDLE
        self.last_message = ""
        self.last_sync_time = ""

        self._listeners: list[Callable[[SyncStatus, str], None]] = []
        self._running = False
        self._paused = False
        self._is_syncing = False
        self._sync_lock = threading.Lock()
        self._run_lock = threading.Lock()
        self._current_run: Optional[SyncRun] = None
        self._thread: Optional[threading.Thread] = None
        self._wakeup_event = threading.Event()
        self.watcher: Optional[VaultWatcher] = None
        self._pending_sync = False
        # True after rclone aborts with "Must run --resync"; cleared on next success.
        self.needs_resync = False
        # One-shot flag set only by an explicit user request (request_resync).
        self._force_resync = False

    def register_listener(self, cb: Callable[[SyncStatus, str], None]):
        """Legacy listener registration for backwards compatibility."""
        if cb not in self._listeners:
            self._listeners.append(cb)

    def unregister_listener(self, cb: Callable[[SyncStatus, str], None]):
        """Legacy listener unregistration."""
        if cb in self._listeners:
            self._listeners.remove(cb)

    def _notify(self, status: SyncStatus, msg: str):
        """Dual-channel notification: triggers legacy callbacks and modern EventDispatcher."""
        self.status = status
        self.last_message = msg

        # Legacy channel
        for cb in list(self._listeners):
            try:
                cb(status, msg)
            except Exception as e:
                logger.error(f"Listener callback error: {e}")

        # Modern EventDispatcher pub/sub
        if self.dispatcher and hasattr(self.dispatcher, "emit"):
            try:
                vault_path = self.config.local_vault_path if self.config else None
                self.dispatcher.emit(
                    EventType.STATUS_CHANGED,
                    StatusPayload(status=status, message=msg, vault_name=vault_path)
                )
            except Exception as e:
                logger.error(f"EventDispatcher emit error: {e}")

    def pause(self):
        self._paused = True
        self._notify(SyncStatus.PAUSED, "Sincronización pausada")

    def resume(self):
        self._paused = False
        self._notify(SyncStatus.IDLE, "Sincronización reanudada")

    def trigger_now(self) -> bool:
        if self._is_syncing or self._sync_lock.locked() or self._paused:
            return False
        self._wakeup_event.set()
        return True

    def request_resync(self) -> bool:
        """
        Run the next sync with --resync, on explicit user confirmation only.
        Used to recover after rclone's safety guards abort bisync.
        """
        if self._is_syncing or self._sync_lock.locked():
            return False
        self._force_resync = True
        if self._running and not self._paused:
            self._wakeup_event.set()
        else:
            threading.Thread(target=self._execute_sync, daemon=True).start()
        return True

    def cancel_sync(self):
        """Gracefully request immediate termination of active sync execution."""
        with self._run_lock:
            run = self._current_run
        if run is not None:
            run.cancel()

    def _on_watcher_change(self):
        if self._paused or not self._running:
            return
        if self._is_syncing or self._sync_lock.locked():
            logger.info("Cambios detectados durante sincronización activa. Marcando sincronización pendiente.")
            self._pending_sync = True
            return
        self._wakeup_event.set()

    def _record_sync_history(
        self,
        status: str,
        duration: float,
        files_transferred: List[str],
        bytes_transferred: int = 0,
        error_message: Optional[str] = None,
    ) -> Optional[SyncRunRecord]:
        """
        Record completed, errored, or conflict sync execution in SyncHistoryManager.
        Guaranteed to never raise or disrupt worker synchronization.
        """
        if self.history_manager is None:
            return None
        try:
            run_id = f"sync_{uuid.uuid4().hex[:8]}"
            vault_name = "Principal"
            if self.config:
                try:
                    active = getattr(self.config, "active_vault", None)
                    if not active or not isinstance(getattr(active, "name", None), str):
                        if callable(getattr(self.config, "get_active_vault", None)):
                            cand = self.config.get_active_vault()
                            if isinstance(getattr(cand, "name", None), str):
                                active = cand
                    if active:
                        raw_name = getattr(active, "name", None)
                        if isinstance(raw_name, str) and raw_name.strip():
                            vault_name = raw_name.strip()
                except Exception:
                    vault_name = "Principal"

            record = SyncRunRecord(
                id=run_id,
                timestamp=datetime.now().astimezone().isoformat(),
                vault_name=vault_name,
                status=status.upper(),
                duration_seconds=round(max(0.0, float(duration)), 2),
                files_transferred=list(files_transferred) if files_transferred else [],
                error_message=error_message,
                bytes_transferred=bytes_transferred,
            )
            self.history_manager.record_run(record)
            return record
        except Exception as ex:
            logger.error(f"Failed to record sync history in SyncWorker: {ex}")
            return None

    def _new_run(self, request: SyncRequest) -> SyncRun:
        run = SyncRun(
            request,
            launcher=self._launcher,
            rclone_binary=self.rclone.ensure_rclone_binary(),
            filters_file=self._filters_file or get_filters_file_path(),
            dispatcher=self.dispatcher,
        )
        with self._run_lock:
            # A cancel that reached the run being replaced (e.g. before a stale-lock retry) carries over.
            if self._current_run is not None and self._current_run.cancelled:
                run.cancel()
            self._current_run = run
        return run

    def _fail(self, status: str, message: str, start_time: float, result: Optional[SyncRunResult] = None) -> bool:
        files = result.files if result else []
        total_bytes = result.total_bytes if result else 0
        self._record_sync_history(status, time.time() - start_time, files, total_bytes, message)
        return False

    def _execute_sync(self) -> bool:
        if not self.config.local_vault_path or not self.config.local_vault_path.strip():
            self._notify(SyncStatus.ERROR, "Ruta de vault no configurada")
            self._record_sync_history("ERROR", 0.0, [], 0, "Ruta de vault no configurada")
            return False

        vault_path = Path(self.config.local_vault_path.strip()).resolve()
        if not vault_path.is_dir():
            msg = f"Ruta de vault inválida o no existe: {self.config.local_vault_path}"
            self._notify(SyncStatus.ERROR, msg)
            self._record_sync_history("ERROR", 0.0, [], 0, msg)
            return False

        if not self._sync_lock.acquire(blocking=False):
            return False

        result: Optional[SyncRunResult] = None
        self._is_syncing = True
        self._notify(SyncStatus.SYNCING, "Sincronizando con Google Drive...")
        start_time = time.time()
        try:
            force_resync, self._force_resync = self._force_resync, False
            if force_resync:
                logger.warning("Ejecutando --resync solicitado manualmente por el usuario.")
            request = SyncRequest(
                local_path=self.config.local_vault_path,
                remote_folder=self.config.remote_folder_name,
                resync=force_resync or not self.config.first_sync_done,
                timeout=self.run_timeout,
            )
            run = self._new_run(request)
            self.rclone.ensure_remote_dir(self.config.remote_folder_name)
            result = run.execute()

            if not result.ok and not result.cancelled and not result.timed_out:
                if "Must run --resync to recover" in result.output:
                    logger.warning(
                        "Rclone abortó por guardas de seguridad. No se ejecutará auto-resync. Salida de rclone:\n%s",
                        result.output[-4000:],
                    )
                    msg = "Guardas de seguridad activadas: Se requiere verificación manual antes de cualquier resincronización."
                    self.needs_resync = True
                    self._notify(SyncStatus.ERROR, msg)
                    return self._fail("ERROR", msg, start_time, result)
                if try_recover_stale_lock(result.output):
                    logger.info("Reintentando sincronización tras limpiar lock huérfano...")
                    result = self._new_run(request).execute()

            if result.cancelled:
                logger.info("Sincronización cancelada por el usuario.")
                msg = "Sincronización cancelada por el usuario"
                self._notify(SyncStatus.IDLE, msg)
                return self._fail("PARTIAL" if result.files or result.returncode is None else "ERROR", msg, start_time, result)

            if result.timed_out:
                logger.error(f"Sincronización cancelada por exceso de tiempo (timeout de {self.run_timeout}s)")
                msg = "Tiempo de espera agotado al sincronizar con Google Drive"
                self._notify(SyncStatus.ERROR, msg)
                return self._fail("ERROR", msg, start_time, result)

            if not result.ok:
                logger.error(f"Rclone error ({result.returncode}): {result.output}")
                summary = clean_error_message(result.output) if result.output else "Error en proceso rclone"
                self._notify(SyncStatus.ERROR, f"Fallo de sincronización: {summary[:120]}")
                return self._fail("PARTIAL" if result.files else "ERROR", summary, start_time, result)

            elapsed = time.time() - start_time
            if self.dispatcher and hasattr(self.dispatcher, "emit"):
                self.dispatcher.emit(
                    EventType.BATCH_COMPLETED,
                    BatchPayload(
                        total_files=len(result.files),
                        total_bytes=result.total_bytes,
                        elapsed_seconds=elapsed,
                        files=list(result.files),
                        status="SUCCESS",
                    )
                )
            status = "CONFLICT" if result.conflicts else "SUCCESS"
            err_msg = f"Bisync conflict detected ({len(result.conflicts)} files)" if result.conflicts else None
            self._record_sync_history(status, elapsed, result.files, result.total_bytes, err_msg)

            self.config.first_sync_done = True
            self.needs_resync = False
            self.last_sync_time = time.strftime("%H:%M:%S")
            self.config.last_sync_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.config.last_sync_status = "success"
            self._notify(SyncStatus.SUCCESS, f"Sincronizado con éxito ({self.last_sync_time})")
            return True
        except Exception as e:
            logger.error(f"Sync execution error: {e}")
            self._notify(SyncStatus.ERROR, f"Error: {str(e)}")
            return self._fail("ERROR", str(e), start_time, result)
        finally:
            with self._run_lock:
                self._current_run = None
            self._is_syncing = False
            self._sync_lock.release()
            if self._pending_sync:
                self._pending_sync = False
                logger.info("Ejecutando sincronización pendiente por cambios locales...")
                self._wakeup_event.set()

    def _run_loop(self):
        """Worker background loop with supervisor catch-all to prevent thread termination."""
        while self._running:
            try:
                if not self._paused:
                    self._execute_sync()
            except Exception as loop_err:
                logger.exception(f"Unhandled error in SyncWorker supervisor loop: {loop_err}")
                self._notify(SyncStatus.ERROR, f"Error interno en motor de sincronización: {loop_err}")
                time.sleep(5)

            interval_sec = max(60, self.config.sync_interval_minutes * 60)
            try:
                triggered = self._wakeup_event.wait(timeout=interval_sec)
                if triggered:
                    self._wakeup_event.clear()
            except Exception as wait_err:
                logger.error(f"Error waiting on wakeup event: {wait_err}")
                time.sleep(1)

    def start(self):
        if self._running:
            return
        self._running = True
        if self.config.realtime_sync_enabled and self.config.local_vault_path:
            self.watcher = VaultWatcher(
                callback=self._on_watcher_change,
                debounce_seconds=getattr(self.config, "debounce_delay_seconds", 5),
            )
            self.watcher.start(self.config.local_vault_path)
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        self.cancel_sync()
        if self.watcher:
            self.watcher.stop()
            self.watcher = None
        self._wakeup_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)
