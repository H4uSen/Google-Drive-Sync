from pathlib import Path
from src.utils.paths import (
    get_app_dir,
    get_config_file_path,
    get_log_file_path,
    get_filters_file_path,
)

def test_paths_return_valid_paths():
    app_dir = get_app_dir()
    assert isinstance(app_dir, Path)
    assert app_dir.name in ("obsidian-gdrive-sync", "ObsidianGDriveSync")
    
    config_file = get_config_file_path()
    assert config_file.parent == app_dir
    assert config_file.name == "config.json"
    
    log_file = get_log_file_path()
    assert log_file.parent == app_dir
    assert log_file.name == "sync.log"
    
    filters_file = get_filters_file_path()
    assert filters_file.parent == app_dir
    assert filters_file.name == "filters.txt"

def test_app_dir_permissions_are_restrictive(monkeypatch, tmp_path):
    import sys
    import stat
    if sys.platform.startswith("win"):
        return
    fake_config = tmp_path / "config_home"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(fake_config))
    app_dir = get_app_dir()
    mode = stat.S_IMODE(app_dir.stat().st_mode)
    assert mode == 0o700

