from enum import Enum
import threading
import time
import subprocess
import logging
from typing import Callable
from src.core.config import ConfigData
from src.core.rclone_manager import RcloneManager

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
    lines = [line.strip() for line in err_msg.splitlines() if line.strip()]
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

class SyncWorker:
    def __init__(self, config: ConfigData, rclone_manager: RcloneManager):
        self.config = config
        self.rclone = rclone_manager
        self.status = SyncStatus.IDLE
        self.last_message = ""
        self.last_sync_time = ""
        
        self._listeners: list[Callable[[SyncStatus, str], None]] = []
        self._running = False
        self._paused = False
        self._is_syncing = False
        self._sync_lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._wakeup_event = threading.Event()

    def register_listener(self, cb: Callable[[SyncStatus, str], None]):
        if cb not in self._listeners:
            self._listeners.append(cb)

    def _notify(self, status: SyncStatus, msg: str):
        self.status = status
        self.last_message = msg
        for cb in self._listeners:
            try:
                cb(status, msg)
            except Exception as e:
                logger.error(f"Listener callback error: {e}")

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

    def _execute_sync(self) -> bool:
        if not self.config.local_vault_path or not self.config.local_vault_path.strip():
            self._notify(SyncStatus.ERROR, "Ruta de vault no configurada")
            return False

        if not self._sync_lock.acquire(blocking=False):
            return False

        self._is_syncing = True
        self._notify(SyncStatus.SYNCING, "Sincronizando con Google Drive...")
        try:
            self.rclone.ensure_remote_dir(self.config.remote_folder_name)
            resync = not self.config.first_sync_done
            cmd = self.rclone.build_bisync_command(
                self.config.local_vault_path,
                self.config.remote_folder_name,
                resync=resync,
            )
            try:
                res = subprocess.run(cmd, capture_output=True, text=True, check=True)
            except subprocess.CalledProcessError as sub_err:
                err_text = sub_err.stderr or sub_err.stdout or ""
                if "Must run --resync to recover" in err_text:
                    logger.info("Resincronización requerida por rclone. Reintentando con --resync...")
                    recovery_cmd = self.rclone.build_bisync_command(
                        self.config.local_vault_path,
                        self.config.remote_folder_name,
                        resync=True,
                    )
                    res = subprocess.run(recovery_cmd, capture_output=True, text=True, check=True)
                else:
                    raise sub_err

            self.config.first_sync_done = True
            self.last_sync_time = time.strftime("%H:%M:%S")
            self._notify(SyncStatus.SUCCESS, f"Sincronizado con éxito ({self.last_sync_time})")
            return True
        except subprocess.CalledProcessError as e:
            err_msg = e.stderr or e.stdout or "Error en proceso rclone"
            logger.error(f"Rclone error ({e.returncode}): {err_msg}")
            summary = clean_error_message(err_msg)
            self._notify(SyncStatus.ERROR, f"Fallo de sincronización: {summary[:120]}")
            return False
        except Exception as e:
            logger.error(f"Sync execution error: {e}")
            self._notify(SyncStatus.ERROR, f"Error: {str(e)}")
            return False
        finally:
            self._is_syncing = False
            self._sync_lock.release()

    def _run_loop(self):
        while self._running:
            if not self._paused:
                self._execute_sync()
            
            interval_sec = max(60, self.config.sync_interval_minutes * 60)
            triggered = self._wakeup_event.wait(timeout=interval_sec)
            if triggered:
                self._wakeup_event.clear()

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        self._wakeup_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)
