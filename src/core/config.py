from dataclasses import dataclass, asdict
from pathlib import Path
import json
import shutil
import logging
from src.utils.paths import get_config_file_path

logger = logging.getLogger(__name__)

@dataclass
class ConfigData:
    local_vault_path: str = ""
    remote_folder_name: str = "ObsidianVault"
    sync_interval_minutes: int = 2
    autostart_enabled: bool = False
    first_sync_done: bool = False
    last_sync_timestamp: str = ""
    last_sync_status: str = "idle"
    theme: str = "dark"

    def clean(self):
        if not isinstance(self.sync_interval_minutes, int) or self.sync_interval_minutes < 1:
            self.sync_interval_minutes = 2
        if not self.remote_folder_name.strip():
            self.remote_folder_name = "ObsidianVault"

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
            cfg = ConfigData(**data)
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
        temp_file.replace(self.config_file)
