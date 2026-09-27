import os
import sys
import threading
import logging
from pathlib import Path
from typing import Callable
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileSystemEvent

logger = logging.getLogger(__name__)

IGNORED_EXACT_NAMES = {
    ".git",
    ".gitignore",
    ".git-credentials",
    "workspace.json",
    "workspace-mobile.json",
}

class VaultChangeHandler(FileSystemEventHandler):
    def __init__(self, callback: Callable[[], None], debounce_seconds: float = 5.0):
        super().__init__()
        self.callback = callback
        self.debounce_seconds = float(debounce_seconds)
        self._timer: threading.Timer | None = None
        self._lock = threading.Lock()

    def should_ignore(self, path: str | None) -> bool:
        if not path:
            return True
        norm = path.replace("\\", "/")
        parts = [p for p in norm.split("/") if p]
        if not parts:
            return True

        if ".git" in parts:
            return True

        filename = parts[-1]
        if filename in IGNORED_EXACT_NAMES:
            return True

        if filename.endswith(".tmp") or filename.endswith("~") or filename.endswith(".swp"):
            return True

        if ".obsidian" in parts:
            obsidian_idx = parts.index(".obsidian")
            sub_parts = parts[obsidian_idx + 1:]
            if sub_parts and sub_parts[0] in ("cache", "workspace.json", "workspace-mobile.json"):
                return True
            if len(sub_parts) >= 3 and sub_parts[0] == "plugins" and sub_parts[1] == "obsidian-git" and sub_parts[2] == "data.json":
                return True

        return False

    def _on_valid_change(self):
        with self._lock:
            if self._timer:
                self._timer.cancel()
            self._timer = threading.Timer(self.debounce_seconds, self._fire_callback)
            self._timer.daemon = True
            self._timer.start()

    def _fire_callback(self):
        with self._lock:
            self._timer = None
        try:
            self.callback()
        except Exception as e:
            logger.error(f"Error in vault watcher callback: {e}")

    def on_any_event(self, event: FileSystemEvent):
        # Descartar eventos de directorios puros
        if event.is_directory:
            return

        src_path = getattr(event, "src_path", "")
        if self.should_ignore(src_path):
            return

        dest_path = getattr(event, "dest_path", None)
        if dest_path and self.should_ignore(dest_path):
            return

        self._on_valid_change()

    def stop(self):
        with self._lock:
            if self._timer:
                self._timer.cancel()
                self._timer = None

class VaultWatcher:
    def __init__(self, callback: Callable[[], None], debounce_seconds: float = 5.0):
        self.callback = callback
        self.debounce_seconds = debounce_seconds
        self.handler = VaultChangeHandler(callback=self.callback, debounce_seconds=self.debounce_seconds)
        self.observer: Observer | None = None
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running

    def start(self, vault_path: str):
        if self._running:
            return
        p = Path(vault_path).resolve()
        if not p.is_dir():
            logger.warning(f"No se puede iniciar VaultWatcher: ruta no válida ({vault_path})")
            return
        try:
            self.observer = Observer()
            self.observer.schedule(self.handler, str(p), recursive=True)
            self.observer.daemon = True
            self.observer.start()
            self._running = True
            logger.info(f"VaultWatcher iniciado en {p} (debounce: {self.debounce_seconds}s)")
        except Exception as e:
            logger.error(f"Error al iniciar VaultWatcher: {e}")

    def stop(self):
        self._running = False
        self.handler.stop()
        if self.observer:
            try:
                self.observer.stop()
                self.observer.join(timeout=2)
            except Exception as e:
                logger.debug(f"Error deteniendo observer: {e}")
            self.observer = None
