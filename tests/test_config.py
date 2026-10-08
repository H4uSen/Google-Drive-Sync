"""Tests for ConfigManager and ConfigData: Vaults are the only source of truth."""
import json
import stat
import sys

import pytest

from src.core.config import ConfigData, ConfigManager, VaultProfile
from tests.builders import vault_config

LEGACY_KEYS = {
    "local_vault_path", "remote_folder_name", "sync_interval_minutes", "first_sync_done",
    "last_sync_timestamp", "last_sync_status", "realtime_sync_enabled", "debounce_delay_seconds",
}


def write_json(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")


def test_missing_file_loads_one_default_vault(tmp_path):
    cfg = ConfigManager(config_file=tmp_path / "config.json").load()

    vault = cfg.active_vault
    assert len(cfg.vaults) == 1
    assert (vault.sync_interval_minutes, vault.remote_folder, vault.first_sync_done) == (2, "ObsidianVault", False)
    assert (vault.realtime_sync_enabled, vault.debounce_delay_seconds) == (True, 5)
    assert cfg.autostart_enabled is False


def test_saved_vault_settings_round_trip(tmp_path):
    mgr = ConfigManager(config_file=tmp_path / "config.json")
    cfg = vault_config("/tmp/myvault", "BackupVault", sync_interval_minutes=5, debounce_delay_seconds=10)
    cfg.autostart_enabled = True

    mgr.save(cfg)
    loaded = mgr.load().active_vault

    assert (loaded.local_path, loaded.remote_folder) == ("/tmp/myvault", "BackupVault")
    assert (loaded.sync_interval_minutes, loaded.debounce_delay_seconds) == (5, 10)
    assert mgr.load().autostart_enabled is True


def test_saved_file_has_only_the_vault_shape(tmp_path):
    config_file = tmp_path / "config.json"

    ConfigManager(config_file=config_file).save(vault_config("/v"))

    data = json.loads(config_file.read_text(encoding="utf-8"))
    assert set(data) == {"vaults", "active_vault_id", "autostart_enabled"}


def test_invalid_vault_settings_are_cleaned_on_save(tmp_path):
    mgr = ConfigManager(config_file=tmp_path / "config.json")

    mgr.save(vault_config(sync_interval_minutes=0, debounce_delay_seconds=0))

    loaded = mgr.load().active_vault
    assert (loaded.sync_interval_minutes, loaded.debounce_delay_seconds) == (2, 5)


def test_corrupt_file_falls_back_to_defaults_and_keeps_a_backup(tmp_path):
    config_file = tmp_path / "config.json"
    config_file.write_text("{corrupted_json_content...", encoding="utf-8")

    cfg = ConfigManager(config_file=config_file).load()

    assert cfg.active_vault.sync_interval_minutes == 2
    assert (tmp_path / "config.json.bak").exists()


@pytest.mark.skipif(sys.platform.startswith("win"), reason="POSIX permissions")
def test_config_file_is_private(tmp_path):
    config_file = tmp_path / "config.json"

    ConfigManager(config_file=config_file).save(ConfigData())

    assert stat.S_IMODE(config_file.stat().st_mode) == 0o600


def test_vault_profile_clean_restores_defaults():
    vp = VaultProfile(id="v1", name="", remote_folder="", sync_interval_minutes=0, debounce_delay_seconds=-1)

    vp.clean()

    assert (vp.name, vp.remote_folder) == ("Principal", "ObsidianVault")
    assert (vp.sync_interval_minutes, vp.debounce_delay_seconds) == (2, 5)


# --- Reading files written by older versions ---------------------------------

def test_flat_only_file_becomes_the_first_vault(tmp_path):
    config_file = tmp_path / "config.json"
    write_json(config_file, {
        "local_vault_path": "/legacy/path",
        "remote_folder_name": "LegacyRemote",
        "sync_interval_minutes": 7,
        "first_sync_done": True,
        "realtime_sync_enabled": False,
        "debounce_delay_seconds": 9,
        "last_sync_status": "success",
        "autostart_enabled": True,
    })

    cfg = ConfigManager(config_file=config_file).load()

    assert len(cfg.vaults) == 1
    v = cfg.active_vault
    assert (v.local_path, v.remote_folder, v.sync_interval_minutes) == ("/legacy/path", "LegacyRemote", 7)
    assert (v.first_sync_done, v.realtime_sync_enabled, v.debounce_delay_seconds) == (True, False, 9)
    assert v.last_sync_status == "success"
    assert cfg.autostart_enabled is True


def test_null_vault_path_in_file_loads_as_empty(tmp_path):
    config_file = tmp_path / "config.json"
    write_json(config_file, {"local_vault_path": None, "vaults": None})

    vault = ConfigManager(config_file=config_file).load().active_vault

    assert vault.local_path == ""


def test_vault_list_wins_over_flat_keys_in_a_mixed_file(tmp_path):
    config_file = tmp_path / "config.json"
    write_json(config_file, {
        "vaults": [
            {"id": "a", "name": "A", "local_path": "/a", "remote_folder": "RA"},
            {"id": "b", "name": "B", "local_path": "/b", "remote_folder": "RB"},
        ],
        "active_vault_id": "b",
        "local_vault_path": "/stale",
        "remote_folder_name": "Stale",
    })

    cfg = ConfigManager(config_file=config_file).load()

    assert [(v.local_path, v.remote_folder) for v in cfg.vaults] == [("/a", "RA"), ("/b", "RB")]
    assert cfg.active_vault.id == "b"


def test_loading_an_old_file_does_not_rewrite_it(tmp_path):
    config_file = tmp_path / "config.json"
    write_json(config_file, {"local_vault_path": "/legacy"})
    before = config_file.read_text(encoding="utf-8")

    mgr = ConfigManager(config_file=config_file)
    cfg = mgr.load()
    assert config_file.read_text(encoding="utf-8") == before

    mgr.save(cfg)
    data = json.loads(config_file.read_text(encoding="utf-8"))
    assert not LEGACY_KEYS & set(data)
    assert data["vaults"][0]["local_path"] == "/legacy"


def test_unknown_keys_are_ignored(tmp_path):
    config_file = tmp_path / "config.json"
    write_json(config_file, {
        "vaults": [{"id": "a", "local_path": "/a", "from_the_future": 1}],
        "active_vault_id": "a",
        "also_unknown": True,
    })

    cfg = ConfigManager(config_file=config_file).load()

    assert cfg.active_vault.local_path == "/a"


# --- Several Vaults ----------------------------------------------------------

def test_switching_vault_does_not_copy_settings_between_vaults(tmp_path):
    mgr = ConfigManager(config_file=tmp_path / "config.json")
    a = VaultProfile(id="a", local_path="/a", remote_folder="RA", first_sync_done=True)
    b = VaultProfile(id="b", local_path="/b", remote_folder="RB")
    cfg = ConfigData(vaults=[a, b], active_vault_id="a")

    cfg.active_vault_id = "b"
    mgr.save(cfg)
    loaded = {v.id: v for v in mgr.load().vaults}

    assert (loaded["a"].local_path, loaded["a"].first_sync_done) == ("/a", True)
    assert (loaded["b"].local_path, loaded["b"].remote_folder, loaded["b"].first_sync_done) == ("/b", "RB", False)


def test_add_switch_and_remove_vaults(tmp_path):
    mgr = ConfigManager(config_file=tmp_path / "config.json")
    cfg = mgr.load()
    first_id = cfg.active_vault.id

    second = cfg.add_vault("Segundo Vault", "/path/v2", "RemoteV2")
    assert cfg.set_active_vault(second.id) is True
    mgr.save(cfg)
    loaded = mgr.load()

    assert len(loaded.vaults) == 2
    assert (loaded.active_vault.name, loaded.active_vault.local_path) == ("Segundo Vault", "/path/v2")

    assert loaded.remove_vault(second.id) is True
    assert loaded.active_vault.id == first_id
    assert loaded.remove_vault(first_id) is False
    assert loaded.set_active_vault("missing") is False


def test_new_vault_copies_schedule_settings_from_the_active_vault():
    cfg = vault_config(sync_interval_minutes=15, realtime_sync_enabled=False, debounce_delay_seconds=30,
                       first_sync_done=True, last_sync_status="success")

    new = cfg.add_vault("Otro", "/other", "Other")

    assert (new.sync_interval_minutes, new.realtime_sync_enabled, new.debounce_delay_seconds) == (15, False, 30)
    assert (new.first_sync_done, new.last_sync_status) == (False, "idle")


def test_invalid_active_id_falls_back_to_the_first_vault():
    cfg = ConfigData(vaults=[VaultProfile(id="a"), VaultProfile(id="b")], active_vault_id="gone")

    cfg.clean()

    assert cfg.active_vault.id == "a"
