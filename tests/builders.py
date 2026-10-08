"""Builders for config objects in tests."""
from src.core.config import ConfigData, VaultProfile


def vault_config(local_path: str = "", remote_folder: str = "ObsidianVault", **vault_fields) -> ConfigData:
    """A ConfigData with one active Vault built from the given fields."""
    vault = VaultProfile(local_path=str(local_path), remote_folder=remote_folder, **vault_fields)
    return ConfigData(vaults=[vault], active_vault_id=vault.id)
