import os
import sys
import subprocess
import webbrowser
import threading
import logging
import time
from typing import Callable
from PIL import Image, ImageDraw
import pystray
from src.core.sync_worker import SyncWorker, SyncStatus

logger = logging.getLogger(__name__)

class TrayManager:
    COOLDOWN_SECONDS: float = 900.0  # 15 minutos

    def __init__(
        self,
        worker: SyncWorker,
        on_open_gui: Callable[[], None],
        on_exit: Callable[[], None],
        on_open_logs: Callable[[], None] | None = None,
    ):
        self.worker = worker
        self.on_open_gui = on_open_gui
        self.on_exit = on_exit
        self.on_open_logs = on_open_logs
        self.icon: pystray.Icon | None = None
        self._status_text = "Inactivo"
        self._last_notified_error: str = ""
        self._last_notification_time: float = 0.0

        # Dynamic summaries for modern tray integration (F-14)
        self._vault_name: str = "Principal"
        self._last_sync_time: str = "Nunca"
        self._quota_summary: str = "Desconocida"

    @property
    def _icon(self):
        """Compatibility property for inspection before/after start."""
        if self.icon is None:
            class _DummyIcon:
                def __init__(self, menu):
                    self.menu = menu
            return _DummyIcon(self._build_menu())
        return self.icon

    @staticmethod
    def create_icon_image(color_hex: str) -> Image.Image:
        image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.ellipse((4, 4, 60, 60), fill=color_hex, outline="#FFFFFF", width=3)
        draw.ellipse((20, 20, 44, 44), fill="#FFFFFF")
        return image

    def set_vault_name(self, name: str):
        self._vault_name = name or "Principal"
        self._refresh_menu()

    def set_last_sync(self, time_str: str):
        self._last_sync_time = time_str or "Nunca"
        self._refresh_menu()

    def set_quota_summary(self, quota_str: str):
        self._quota_summary = quota_str or "Desconocida"
        self._refresh_menu()

    def _refresh_menu(self):
        if self.icon and hasattr(self.icon, "update_menu"):
            try:
                self.icon.menu = self._build_menu()
                self.icon.update_menu()
            except Exception as e:
                logger.debug(f"Error refreshing tray menu: {e}")

    def _build_menu(self) -> pystray.Menu:
        return pystray.Menu(
            pystray.MenuItem("Abrir Ventana Principal", lambda *_: self.on_open_gui(), default=True),
            pystray.MenuItem("Sincronizar Ahora", lambda *_: self.worker.trigger_now()),
            pystray.MenuItem(
                lambda text: "Reanudar Sincronización" if self.worker.status == SyncStatus.PAUSED else "Pausar Sincronización",
                lambda *_: self._toggle_pause(),
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(lambda text: f"Vault: {self._vault_name}", None, enabled=False),
            pystray.MenuItem(lambda text: f"Estado: {self._status_text}", None, enabled=False),
            pystray.MenuItem(lambda text: f"Última sync: {self._last_sync_time}", None, enabled=False),
            pystray.MenuItem(lambda text: f"Cuota: {self._quota_summary}", None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Abrir Carpeta Local", lambda *_: self.open_vault_folder()),
            pystray.MenuItem("Abrir Google Drive", lambda *_: self.open_gdrive_web()),
            pystray.MenuItem("Ver Registros / Diagnóstico", lambda *_: self.open_logs()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Salir", lambda *_: self.on_exit()),
        )

    def _toggle_pause(self):
        if self.worker.status == SyncStatus.PAUSED:
            self.worker.resume()
        else:
            self.worker.pause()

    def open_vault_folder(self):
        path = self.worker.config.active_vault.local_path
        if not path:
            return
        try:
            if sys.platform.startswith("win"):
                os.startfile(path)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except Exception as e:
            logger.error(f"Error opening vault folder: {e}")

    def open_gdrive_web(self):
        try:
            webbrowser.open("https://drive.google.com")
        except Exception as e:
            logger.error(f"Error opening Google Drive in browser: {e}")

    def open_logs(self):
        try:
            self.on_open_gui()
            if self.on_open_logs:
                self.on_open_logs()
        except Exception as e:
            logger.error(f"Error opening logs from tray: {e}")

    def notify_conflict(self, filename: str):
        self.notify("Conflicto detectado", f"Conflicto en archivo: {filename}")

    def notify_batch_complete(self, file_count: int, total_bytes: int = 0):
        try:
            from src.gui.app_window import format_byte_size
            size_str = format_byte_size(total_bytes) if total_bytes > 0 else ""
        except Exception:
            size_str = f"{total_bytes} B" if total_bytes > 0 else ""
        msg = f"Se sincronizaron {file_count} archivos ({size_str})" if size_str else f"Se sincronizaron {file_count} archivos"
        self.notify("Sincronización completada", msg)

    def notify(self, title: str, message: str):
        if self.icon and hasattr(self.icon, "notify"):
            try:
                self.icon.notify(message, title)
            except Exception as e:
                logger.warning(f"Error mostrando notificación de escritorio: {e}")

    def update_status(self, status: SyncStatus, msg: str):
        self._status_text = msg
        if status == SyncStatus.SUCCESS and getattr(self.worker, "last_sync_time", ""):
            self.set_last_sync(self.worker.last_sync_time)
        if self.icon:
            try:
                self.icon.icon = self.create_icon_image(status.color)
                self.icon.title = f"Obsidian GDrive Sync: {msg}"
            except Exception as e:
                logger.debug(f"Error updating tray icon: {e}")

        # Lógica de notificaciones con deduplicación y cooldown
        if status == SyncStatus.ERROR:
            now = time.time()
            is_same_error = (msg == self._last_notified_error)
            within_cooldown = (now - self._last_notification_time < self.COOLDOWN_SECONDS)

            if not (is_same_error and within_cooldown):
                self._last_notified_error = msg
                self._last_notification_time = now
                self.notify("Obsidian GDrive Sync - Error", msg)
        elif status in (SyncStatus.SUCCESS, SyncStatus.IDLE):
            self._last_notified_error = ""
            self._last_notification_time = 0.0

    def start(self):
        img = self.create_icon_image(SyncStatus.IDLE.color)
        self.icon = pystray.Icon("obsidian_sync", img, "Obsidian GDrive Sync", menu=self._build_menu())
        threading.Thread(target=self.icon.run, daemon=True).start()

    def stop(self):
        if self.icon:
            try:
                self.icon.stop()
            except Exception as e:
                logger.debug(f"Error stopping tray: {e}")
