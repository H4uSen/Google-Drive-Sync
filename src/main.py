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
    try:
        if lock_file.exists():
            # Comprobar si el proceso anterior sigue vivo
            pid_str = lock_file.read_text(encoding="utf-8").strip()
            if pid_str.isdigit():
                pid = int(pid_str)
                try:
                    os.kill(pid, 0)
                    logger.warning(f"Otra instancia de la aplicación ya está en ejecución (PID: {pid}).")
                    return False
                except (OSError, ProcessLookupError):
                    pass # Proceso anterior murió
        lock_file.write_text(str(os.getpid()), encoding="utf-8")
        return True
    except Exception as e:
        logger.error(f"Error gestionando archivo de bloqueo: {e}")
        return True

def release_single_instance_lock():
    lock_file = get_app_dir() / "app.lock"
    try:
        if lock_file.exists():
            lock_file.unlink()
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

    def on_exit():
        logger.info("Deteniendo Obsidian GDrive Sync...")
        worker.stop()
        tray.stop()
        release_single_instance_lock()
        app.after(0, app.destroy)
        sys.exit(0)

    tray = TrayManager(worker=worker, on_open_gui=on_open_gui, on_exit=on_exit)
    worker.register_listener(tray.update_status)

    try:
        tray.start()
    except Exception as e:
        logger.warning(f"No se pudo iniciar el icono en System Tray: {e}")

    # Si se pasa --minimized no mostramos la ventana al iniciar
    if "--minimized" in sys.argv:
        app.withdraw()
    
    try:
        app.mainloop()
    finally:
        release_single_instance_lock()

if __name__ == "__main__":
    main()
