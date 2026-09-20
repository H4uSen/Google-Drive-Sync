import sys
import shutil
import subprocess
import urllib.request
import zipfile
import tarfile
import logging
from pathlib import Path
from src.core.filter_rules import write_filters_file
from src.utils.paths import get_filters_file_path, get_app_dir

logger = logging.getLogger(__name__)

class RcloneManager:
    def __init__(self, rclone_binary: str | None = None):
        self._binary = rclone_binary or self.find_rclone_binary()

    @property
    def binary_path(self) -> str:
        return self._binary

    @staticmethod
    def get_local_binary_path() -> Path:
        bin_name = "rclone.exe" if sys.platform.startswith("win") else "rclone"
        return get_app_dir() / "bin" / bin_name

    @classmethod
    def find_rclone_binary(cls) -> str:
        system_bin = shutil.which("rclone")
        if system_bin:
            return system_bin
        
        local_bin = cls.get_local_binary_path()
        if local_bin.exists() and os_is_executable(local_bin):
            return str(local_bin)
            
        return "rclone"

    def is_remote_configured(self, remote_name: str = "gdrive") -> bool:
        try:
            result = subprocess.run(
                [self._binary, "listremotes"],
                capture_output=True,
                text=True,
                check=True,
            )
            remotes = [r.strip().rstrip(":") for r in result.stdout.splitlines()]
            return remote_name in remotes
        except Exception as e:
            logger.debug(f"Error listing remotes: {e}")
            return False

    def get_auth_command(self, remote_name: str = "gdrive") -> list[str]:
        return [self._binary, "config", "create", remote_name, "drive", "scope=drive"]

    def build_bisync_command(
        self,
        local_path: str,
        remote_folder: str,
        resync: bool = False,
        filters_file: Path | None = None,
    ) -> list[str]:
        target_filters = filters_file or get_filters_file_path()
        if not target_filters.exists():
            write_filters_file(target_filters)

        clean_remote = remote_folder.strip().strip("/")
        remote_target = f"gdrive:{clean_remote}"
        cmd = [
            self._binary,
            "bisync",
            str(local_path),
            remote_target,
            "--filters-file",
            str(target_filters),
            "--drive-chunk-size",
            "32M",
            "--conflict-resolve",
            "none",
            "--conflict-loser",
            "pathname",
            "--check-access",
            "--retries",
            "3",
            "-v",
        ]
        if resync:
            cmd.append("--resync")
        return cmd

def os_is_executable(path: Path) -> bool:
    import os
    return os.access(path, os.X_OK)
