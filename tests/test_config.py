"""Tests for ConfigManager and ConfigData."""
import pytest
import json
from pathlib import Path
from src.core.config import ConfigManager, ConfigData

def test_default_config(tmp_path):
    config_file = tmp_path / "config.json"
    manager = ConfigManager(config_file=config_file)
    cfg = manager.load()
    assert cfg.sync_interval_minutes == 2
    assert cfg.remote_folder_name == "ObsidianVault"
    assert cfg.first_sync_done is False

def test_save_and_load_config(tmp_path):
    config_file = tmp_path / "config.json"
    manager = ConfigManager(config_file=config_file)
    cfg = ConfigData(
        local_vault_path="/tmp/myvault",
        remote_folder_name="BackupVault",
        sync_interval_minutes=5,
    )
    manager.save(cfg)
    loaded = manager.load()
    assert loaded.local_vault_path == "/tmp/myvault"
    assert loaded.sync_interval_minutes == 5
    assert loaded.remote_folder_name == "BackupVault"

def test_interval_validation_clamping(tmp_path):
    config_file = tmp_path / "config.json"
    manager = ConfigManager(config_file=config_file)
    cfg = ConfigData(sync_interval_minutes=0)
    manager.save(cfg)
    loaded = manager.load()
    assert loaded.sync_interval_minutes >= 1

def test_corrupt_config_fallback(tmp_path):
    config_file = tmp_path / "config.json"
    config_file.write_text("{corrupted_json_content...", encoding="utf-8")
    manager = ConfigManager(config_file=config_file)
    cfg = manager.load()
    assert cfg.sync_interval_minutes == 2
    assert (tmp_path / "config.json.bak").exists()

def test_config_file_permissions(tmp_path):
    import sys
    import stat
    if sys.platform.startswith("win"):
        return
    config_file = tmp_path / "config.json"
    manager = ConfigManager(config_file=config_file)
    manager.save(ConfigData())
    mode = stat.S_IMODE(config_file.stat().st_mode)
    assert mode == 0o600

