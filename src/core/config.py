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

@dataclass
class ConfigData:
    vaults: list[VaultProfile] = field(default_factory=list)
    active_vault_id: str = "default"
    autostart_enabled: bool = False
    # Legacy fields maintained for 100% backward compatibility in constructor, accessors, and serialization
    local_vault_path: str = ""
    remote_folder_name: str = "ObsidianVault"
    sync_interval_minutes: int = 2
    first_sync_done: bool = False
    last_sync_timestamp: str = ""
    last_sync_status: str = "idle"
    realtime_sync_enabled: bool = True
    debounce_delay_seconds: int = 5

    def __post_init__(self):
        converted = []
        for v in self.vaults:
            if isinstance(v, dict):
                converted.append(VaultProfile(**v))
            elif isinstance(v, VaultProfile):
                converted.append(v)
        self.vaults = converted

        if not self.vaults:
            # Migration: populate initial vault profile from legacy fields
            initial_vault = VaultProfile(
                id=self.active_vault_id or "default",
                name="Principal",
                local_path=self.local_vault_path,
                remote_folder=self.remote_folder_name or "ObsidianVault",
                sync_interval_minutes=self.sync_interval_minutes,
                realtime_sync_enabled=self.realtime_sync_enabled,
                debounce_delay_seconds=self.debounce_delay_seconds,
                first_sync_done=self.first_sync_done,
                last_sync_timestamp=self.last_sync_timestamp,
                last_sync_status=self.last_sync_status,
            )
            initial_vault.clean()
            self.vaults = [initial_vault]
            self.active_vault_id = initial_vault.id

        self.clean()

    def get_active_vault(self) -> VaultProfile:
        for v in self.vaults:
            if v.id == self.active_vault_id:
                return v
        return self.vaults[0]

    @property
    def active_vault(self) -> VaultProfile:
        return self.get_active_vault()

    def set_active_vault(self, vault_id: str) -> bool:
        target = next((v for v in self.vaults if v.id == vault_id), None)
        if not target:
            return False
        # Sync current active vault from legacy fields before switching
        self._sync_active_from_legacy()
        self.active_vault_id = target.id
        self._sync_legacy_from_active()
        return True

    def add_vault(self, name: str, local_path: str = "", remote_folder: str = "ObsidianVault") -> VaultProfile:
        vault_id = f"vault_{uuid.uuid4().hex[:8]}"
        new_vault = VaultProfile(
            id=vault_id,
            name=name.strip() or "Nuevo Vault",
            local_path=local_path,
            remote_folder=remote_folder.strip() or "ObsidianVault",
            sync_interval_minutes=self.sync_interval_minutes,
            realtime_sync_enabled=self.realtime_sync_enabled,
            debounce_delay_seconds=self.debounce_delay_seconds,
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
        self._sync_legacy_from_active()
        return True

    def _sync_legacy_from_active(self):
        active = self.get_active_vault()
        self.local_vault_path = active.local_path
        self.remote_folder_name = active.remote_folder
        self.sync_interval_minutes = active.sync_interval_minutes
        self.realtime_sync_enabled = active.realtime_sync_enabled
        self.debounce_delay_seconds = active.debounce_delay_seconds
        self.first_sync_done = active.first_sync_done
        self.last_sync_timestamp = active.last_sync_timestamp
        self.last_sync_status = active.last_sync_status

    def _sync_active_from_legacy(self):
        if not self.vaults:
            return
        active = self.get_active_vault()
        active.local_path = self.local_vault_path
        active.remote_folder = self.remote_folder_name
        active.sync_interval_minutes = self.sync_interval_minutes
        active.realtime_sync_enabled = self.realtime_sync_enabled
        active.debounce_delay_seconds = self.debounce_delay_seconds
        active.first_sync_done = self.first_sync_done
        active.last_sync_timestamp = self.last_sync_timestamp
        active.last_sync_status = self.last_sync_status

    def clean(self):
        if not self.vaults:
            default_v = VaultProfile()
            self.vaults = [default_v]
            self.active_vault_id = default_v.id
        elif not any(v.id == self.active_vault_id for v in self.vaults):
            self.active_vault_id = self.vaults[0].id

        self._sync_active_from_legacy()
        for v in self.vaults:
            v.clean()
        self._sync_legacy_from_active()

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
            fields = ConfigData.__dataclass_fields__.keys()
            cfg = ConfigData(**{k: v for k, v in data.items() if k in fields})
            cfg.clean()
            return cfg
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
