import sys
import os
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

APP_NAME = "ObsidianGDriveSync"
DESKTOP_FILENAME = "obsidian-gdrive-sync.desktop"
WIN_REG_SUBKEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def is_autostart_supported() -> bool:
    return sys.platform.startswith(("linux", "win"))


def get_project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def get_linux_autostart_dir() -> Path:
    config_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    autostart_dir = config_home / "autostart"
    autostart_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not sys.platform.startswith("win"):
        try:
            os.chmod(autostart_dir, 0o700)
        except OSError:
            pass
    return autostart_dir


def get_linux_desktop_file_path() -> Path:
    return get_linux_autostart_dir() / DESKTOP_FILENAME


def get_autostart_command() -> str:
    exe = sys.executable
    if sys.platform.startswith("win"):
        # Buscar pythonw.exe para evitar ventana de consola negra
        pythonw = Path(exe).with_name("pythonw.exe")
        if pythonw.exists():
            exe = str(pythonw)
    return f'"{exe}" -m src.main --minimized'


def set_autostart_linux(enabled: bool) -> bool:
    desktop_file = get_linux_desktop_file_path()
    if enabled:
        project_root = get_project_root()
        cmd = get_autostart_command()
        content = (
            "[Desktop Entry]\n"
            "Type=Application\n"
            f"Name={APP_NAME}\n"
            "Comment=Sincronización continua de Obsidian Vault con Google Drive\n"
            f"Exec={cmd}\n"
            f"Path={project_root}\n"
            "Terminal=false\n"
            "Categories=Utility;Sync;\n"
            "X-GNOME-Autostart-enabled=true\n"
        )
        try:
            desktop_file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            desktop_file.write_text(content, encoding="utf-8")
            desktop_file.chmod(0o700)
            return True
        except Exception as e:
            logger.error(f"Error escribiendo archivo autostart Linux: {e}")
            return False
    else:
        try:
            desktop_file.unlink(missing_ok=True)
            return True
        except Exception as e:
            logger.error(f"Error eliminando archivo autostart Linux: {e}")
            return False


def is_autostart_enabled_linux() -> bool:
    return get_linux_desktop_file_path().is_file()


def set_autostart_windows(enabled: bool) -> bool:
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, WIN_REG_SUBKEY, 0, winreg.KEY_SET_VALUE
        )
        with key:
            if enabled:
                cmd = get_autostart_command()
                winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, cmd)
            else:
                try:
                    winreg.DeleteValue(key, APP_NAME)
                except FileNotFoundError:
                    pass
        return True
    except Exception as e:
        logger.error(f"Error modificando clave de registro de autostart en Windows: {e}")
        return False


def is_autostart_enabled_windows() -> bool:
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, WIN_REG_SUBKEY, 0, winreg.KEY_READ
        )
        with key:
            val, _ = winreg.QueryValueEx(key, APP_NAME)
            return bool(val)
    except Exception:
        return False


def set_autostart(enabled: bool) -> bool:
    if sys.platform.startswith("win"):
        return set_autostart_windows(enabled)
    elif sys.platform.startswith("linux"):
        return set_autostart_linux(enabled)
    return False


def is_autostart_enabled() -> bool:
    if sys.platform.startswith("win"):
        return is_autostart_enabled_windows()
    elif sys.platform.startswith("linux"):
        return is_autostart_enabled_linux()
    return False
