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
    ):
        self.worker = worker
        self.on_open_gui = on_open_gui
        self.on_exit = on_exit
        self.icon: pystray.Icon | None = None
        self._status_text = "Inactivo"
        self._last_notified_error: str = ""
        self._last_notification_time: float = 0.0

    @staticmethod
    def create_icon_image(color_hex: str) -> Image.Image:
        image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.ellipse((4, 4, 60, 60), fill=color_hex, outline="#FFFFFF", width=3)
        draw.ellipse((20, 20, 44, 44), fill="#FFFFFF")
        return image

    def _build_menu(self) -> pystray.Menu:
        return pystray.Menu(
            pystray.MenuItem("Abrir Ventana Principal", lambda: self.on_open_gui(), default=True),
            pystray.MenuItem("Sincronizar Ahora", lambda: self.worker.trigger_now()),
            pystray.MenuItem(
                lambda text: "Reanudar Sincronización" if self.worker.status == SyncStatus.PAUSED else "Pausar Sincronización",
                lambda: self._toggle_pause(),
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(lambda text: f"Estado: {self._status_text}", None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Salir", lambda: self.on_exit()),
        )

    def _toggle_pause(self):
        if self.worker.status == SyncStatus.PAUSED:
            self.worker.resume()
        else:
            self.worker.pause()

    def notify(self, title: str, message: str):
        if self.icon and hasattr(self.icon, "notify"):
            try:
                self.icon.notify(message, title)
            except Exception as e:
                logger.warning(f"Error mostrando notificación de escritorio: {e}")

    def update_status(self, status: SyncStatus, msg: str):
        self._status_text = msg
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
