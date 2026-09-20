import sys
import os
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

def generate_linux_desktop_entry(exec_path: str) -> str:
    return f"""[Desktop Entry]
Type=Application
Name=Obsidian GDrive Sync
Exec={exec_path} --minimized
Icon=utilities-sync
Comment=Obsidian Vault GDrive Synchronizer
Terminal=false
StartupNotify=false
Categories=Utility;FileTools;
"""

def set_autostart(enabled: bool) -> bool:
    try:
        if sys.platform.startswith("linux"):
            autostart_dir = Path.home() / ".config" / "autostart"
            desktop_file = autostart_dir / "obsidian-gdrive-sync.desktop"
            if enabled:
                autostart_dir.mkdir(parents=True, exist_ok=True)
                desktop_file.write_text(generate_linux_desktop_entry(sys.executable), encoding="utf-8")
            else:
                if desktop_file.exists():
                    desktop_file.unlink()
            return True
        elif sys.platform.startswith("win"):
            import winreg
            key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_ALL_ACCESS)
            app_name = "ObsidianGDriveSync"
            if enabled:
                cmd = f'"{sys.executable}" --minimized'
                winreg.SetValueEx(key, app_name, 0, winreg.REG_SZ, cmd)
            else:
                try:
                    winreg.DeleteValue(key, app_name)
                except FileNotFoundError:
                    pass
            winreg.CloseKey(key)
            return True
    except Exception as e:
        logger.error(f"Error toggling autostart: {e}")
        return False
    return False
