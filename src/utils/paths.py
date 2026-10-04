import sys
import os
from pathlib import Path

def get_app_dir() -> Path:
    if sys.platform.startswith("win"):
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        app_dir = base / "ObsidianGDriveSync"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
        app_dir = base / "obsidian-gdrive-sync"
    
    app_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not sys.platform.startswith("win"):
        try:
            os.chmod(app_dir, 0o700)
        except OSError:
            pass
    return app_dir

def get_config_file_path() -> Path:
    return get_app_dir() / "config.json"

def get_log_file_path() -> Path:
    return get_app_dir() / "sync.log"

def get_filters_file_path() -> Path:
    return get_app_dir() / "filters.txt"

def get_history_file_path() -> Path:
    return get_app_dir() / "history.json"

