"""
Application logging configuration and GuiLogHandler singleton integration.
"""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from threading import Lock
from typing import Optional

from src.utils.paths import get_log_file_path
from src.utils.log_handler import GuiLogHandler

_gui_log_handler: Optional[GuiLogHandler] = None
_gui_handler_lock = Lock()


def get_gui_log_handler(max_entries: int = 1000) -> GuiLogHandler:
    """
    Thread-safe accessor/singleton for the shared GuiLogHandler instance.
    """
    global _gui_log_handler
    if _gui_log_handler is None:
        with _gui_handler_lock:
            if _gui_log_handler is None:
                _gui_log_handler = GuiLogHandler(max_entries=max_entries)
    return _gui_log_handler


def reset_gui_log_handler() -> None:
    """
    Reset the shared GuiLogHandler instance (useful for test isolation).
    """
    global _gui_log_handler
    with _gui_handler_lock:
        if _gui_log_handler is not None:
            old_handler = _gui_log_handler
            # Clean up old_handler from all known loggers
            known_loggers = list(logging.root.manager.loggerDict.keys()) + ["", "src", "obsidian_sync"]
            for name in known_loggers:
                lg = logging.getLogger(name)
                if old_handler in lg.handlers:
                    lg.removeHandler(old_handler)
            old_handler.clear()
            _gui_log_handler = None


def setup_logger(name: str = "obsidian_sync") -> logging.Logger:
    """
    Configures and returns the application logger with:
    - RotatingFileHandler (5MB, 3 backups) to ~/.config/obsidian-gdrive-sync/sync.log
    - StreamHandler to console
    - GuiLogHandler in-memory ring-buffer for GUI inspection and diagnostics
    Also ensures propagation from 'src' loggers into the GuiLogHandler.
    """
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 1. File and Console handlers on target logger
    has_file = any(isinstance(h, RotatingFileHandler) for h in logger.handlers)
    has_stream = any(
        isinstance(h, logging.StreamHandler) and not isinstance(h, (RotatingFileHandler, GuiLogHandler))
        for h in logger.handlers
    )

    if not has_file:
        try:
            log_file = get_log_file_path()
            file_handler = RotatingFileHandler(
                log_file, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
            )
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
        except Exception:
            pass

    if not has_stream:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    # 2. Attach shared GuiLogHandler to target logger
    gui_handler = get_gui_log_handler()
    for h in list(logger.handlers):
        if isinstance(h, GuiLogHandler) and h is not gui_handler:
            logger.removeHandler(h)
    if gui_handler not in logger.handlers:
        gui_handler.setFormatter(formatter)
        logger.addHandler(gui_handler)

    # 3. Wire the 'src' package logger so child modules (src.core.*, src.tray.*)
    # also emit into GuiLogHandler
    src_logger = logging.getLogger("src")
    src_logger.setLevel(logging.INFO)
    for h in list(src_logger.handlers):
        if isinstance(h, GuiLogHandler) and h is not gui_handler:
            src_logger.removeHandler(h)
    if gui_handler not in src_logger.handlers:
        gui_handler.setFormatter(formatter)
        src_logger.addHandler(gui_handler)

    return logger
