import sys
import os
from pathlib import Path
from src.utils.logger import setup_logger
from src.utils.paths import get_app_dir
from src.core.config import ConfigManager
from src.core.rclone_manager import RcloneManager
from src.core.sync_worker import SyncWorker
from src.tray.tray_icon import TrayManager
from src.gui.app_window import MainWindow

logger = setup_logger("obsidian_sync")

def acquire_single_instance_lock() -> bool:
    lock_file = get_app_dir() / "app.lock"

    def _write_pid_atomic() -> bool:
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        fd = os.open(lock_file, flags, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(str(os.getpid()))
        return True

    try:
        return _write_pid_atomic()
    except FileExistsError:
        try:
            pid_str = lock_file.read_text(encoding="utf-8").strip()
            if pid_str.isdigit():
                pid = int(pid_str)
                try:
                    os.kill(pid, 0)
                    logger.warning(f"Otra instancia de la aplicación ya está en ejecución (PID: {pid}).")
                    return False
                except (OSError, ProcessLookupError):
                    pass
            lock_file.unlink(missing_ok=True)
            return _write_pid_atomic()
        except Exception as stale_err:
            logger.error(f"Error gestionando archivo de bloqueo obsoleto: {stale_err}")
            return False
    except Exception as e:
        logger.error(f"Error gestionando archivo de bloqueo: {e}")
        return False

def release_single_instance_lock():
    try:
        (get_app_dir() / "app.lock").unlink(missing_ok=True)
    except Exception:
        pass

def main():
    if not acquire_single_instance_lock():
        print("Obsidian GDrive Sync ya está ejecutándose en segundo plano (revisa el icono en la barra de tareas).")
        sys.exit(0)

    logger.info("Iniciando Obsidian GDrive Sync...")
    config_mgr = ConfigManager()
    cfg = config_mgr.load()
    rclone_mgr = RcloneManager()
    worker = SyncWorker(config=cfg, rclone_manager=rclone_mgr)

    app = MainWindow(config_manager=config_mgr, worker=worker, rclone_mgr=rclone_mgr)

    def on_open_gui():
        app.after(0, app.deiconify)
        app.after(0, app.lift)

    def on_open_logs():
        def _show_logs():
            app.deiconify()
            app.lift()
            if hasattr(app, "tabview") and app.tabview:
                try:
                    app.tabview.set("Diagnósticos")
                except Exception:
                    pass
        app.after(0, _show_logs)

    def on_exit():
        logger.info("Deteniendo Obsidian GDrive Sync...")
        worker.stop()
        tray.stop()
        release_single_instance_lock()
        app.after(0, app.quit)

    tray = TrayManager(worker=worker, on_open_gui=on_open_gui, on_exit=on_exit, on_open_logs=on_open_logs)
    worker.register_listener(tray.update_status)

    try:
        tray.start()
    except Exception as e:
        logger.warning(f"No se pudo iniciar el icono en System Tray: {e}")

    # Si se pasa --minimized ocultamos la ventana y evaluamos auto-arranque
    if "--minimized" in sys.argv:
        app.withdraw()
        if app.can_auto_start_sync():
            logger.info("Iniciando motor de sincronización automáticamente (--minimized)...")
            app.start_sync_engine()
        else:
            logger.info("Obsidian GDrive Sync iniciado en segundo plano; esperando configuración.")
            tray.notify(
                "Obsidian GDrive Sync",
                "Aplicación iniciada en segundo plano. Abre la ventana para configurar tu Vault."
            )
    
    try:
        app.mainloop()
    finally:
        release_single_instance_lock()

if __name__ == "__main__":
    main()
