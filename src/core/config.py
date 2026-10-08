from dataclasses import dataclass, field, asdict
from pathlib import Path
import json
import shutil
import logging
import sys
import os
import uuid
from src.utils.paths import get_config_file_path

logger = logging.getLogger(__name__)

@dataclass
class VaultProfile:
    id: str = "default"
    name: str = "Principal"
    local_path: str = ""
    remote_folder: str = "ObsidianVault"
    sync_interval_minutes: int = 2
    realtime_sync_enabled: bool = True
    debounce_delay_seconds: int = 5
    first_sync_done: bool = False
    last_sync_timestamp: str = ""
    last_sync_status: str = "idle"

    def clean(self):
        if not isinstance(self.sync_interval_minutes, int) or self.sync_interval_minutes < 1:
            self.sync_interval_minutes = 2
        if not isinstance(self.debounce_delay_seconds, int) or self.debounce_delay_seconds < 1:
            self.debounce_delay_seconds = 5
        if not self.remote_folder or not self.remote_folder.strip():
            self.remote_folder = "ObsidianVault"
        if not self.name or not self.name.strip():
            self.name = "Principal"

# Keys of the single-vault format written by older versions, read only to migrate.
LEGACY_VAULT_KEYS = {
    "local_vault_path": "local_path",
    "remote_folder_name": "remote_folder",
    "sync_interval_minutes": "sync_interval_minutes",
    "realtime_sync_enabled": "realtime_sync_enabled",
    "debounce_delay_seconds": "debounce_delay_seconds",
    "first_sync_done": "first_sync_done",
    "last_sync_timestamp": "last_sync_timestamp",
    "last_sync_status": "last_sync_status",
}


def _vault_from_dict(data: dict) -> VaultProfile:
    fields = VaultProfile.__dataclass_fields__.keys()
    return VaultProfile(**{k: v for k, v in data.items() if k in fields})


@dataclass
class ConfigData:
    vaults: list[VaultProfile] = field(default_factory=list)
    active_vault_id: str = "default"
    autostart_enabled: bool = False

    def __post_init__(self):
        self.clean()

    @classmethod
    def from_dict(cls, data: dict) -> "ConfigData":
        """Build from a saved config.json, including files written before multi-vault support."""
        raw_vaults = data.get("vaults")
        if raw_vaults:
            vaults = [_vault_from_dict(v) for v in raw_vaults if isinstance(v, dict)]
            active_id = data.get("active_vault_id", "default")
        else:
            legacy = {new: data[old] for old, new in LEGACY_VAULT_KEYS.items() if old in data}
            vault = VaultProfile(id=data.get("active_vault_id") or "default", **legacy)
            vaults, active_id = [vault], vault.id
        return cls(
            vaults=vaults,
            active_vault_id=active_id,
            autostart_enabled=bool(data.get("autostart_enabled", False)),
        )

    def get_active_vault(self) -> VaultProfile:
        for v in self.vaults:
            if v.id == self.active_vault_id:
                return v
        return self.vaults[0]

    @property
    def active_vault(self) -> VaultProfile:
        return self.get_active_vault()

    def set_active_vault(self, vault_id: str) -> bool:
        if not any(v.id == vault_id for v in self.vaults):
            return False
        self.active_vault_id = vault_id
        return True

    def add_vault(self, name: str, local_path: str = "", remote_folder: str = "ObsidianVault") -> VaultProfile:
        active = self.active_vault
        new_vault = VaultProfile(
            id=f"vault_{uuid.uuid4().hex[:8]}",
            name=name.strip() or "Nuevo Vault",
            local_path=local_path,
            remote_folder=remote_folder.strip() or "ObsidianVault",
            sync_interval_minutes=active.sync_interval_minutes,
            realtime_sync_enabled=active.realtime_sync_enabled,
            debounce_delay_seconds=active.debounce_delay_seconds,
        )
        new_vault.clean()
        self.vaults.append(new_vault)
        return new_vault

    def remove_vault(self, vault_id: str) -> bool:
        if len(self.vaults) <= 1:
            return False
        target = next((v for v in self.vaults if v.id == vault_id), None)
        if not target:
            return False
        self.vaults.remove(target)
        if self.active_vault_id == vault_id:
            self.active_vault_id = self.vaults[0].id
        return True

    def clean(self):
        if not self.vaults:
            default_v = VaultProfile()
            self.vaults = [default_v]
            self.active_vault_id = default_v.id
        elif not any(v.id == self.active_vault_id for v in self.vaults):
            self.active_vault_id = self.vaults[0].id
        for v in self.vaults:
            v.clean()

class ConfigManager:
    def __init__(self, config_file: Path | None = None):
        self.config_file = config_file or get_config_file_path()

    def load(self) -> ConfigData:
        if not self.config_file.exists():
            default = ConfigData()
            self.save(default)
            return default
        try:
            with open(self.config_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            return ConfigData.from_dict(data)
        except Exception as e:
            logger.error(f"Error reading config, restoring backup: {e}")
            bak = self.config_file.with_suffix(".json.bak")
            try:
                shutil.copyfile(self.config_file, bak)
            except Exception as copy_err:
                logger.error(f"Failed to create config backup: {copy_err}")
            default = ConfigData()
            self.save(default)
            return default

    def save(self, config: ConfigData) -> None:
        config.clean()
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        temp_file = self.config_file.with_suffix(".tmp")
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(asdict(config), f, indent=2, ensure_ascii=False)
        if not sys.platform.startswith("win"):
            try:
                os.chmod(temp_file, 0o600)
            except OSError:
                pass
        temp_file.replace(self.config_file)
