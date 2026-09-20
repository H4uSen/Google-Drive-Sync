import sys
import shutil
import subprocess
import urllib.request
import zipfile
import stat
import io
import logging
from pathlib import Path
from src.core.filter_rules import write_filters_file
from src.utils.paths import get_filters_file_path, get_app_dir

logger = logging.getLogger(__name__)

class RcloneManager:
    def __init__(self, rclone_binary: str | None = None):
        self._explicit_binary = rclone_binary
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

        # Check project root bin
        project_bin = Path(__file__).resolve().parent.parent.parent / "bin" / ("rclone.exe" if sys.platform.startswith("win") else "rclone")
        if project_bin.exists() and os_is_executable(project_bin):
            return str(project_bin)
            
        return "rclone"

    def ensure_rclone_binary(self) -> str:
        if self._explicit_binary:
            return self._explicit_binary

        current = self.find_rclone_binary()
        if current != "rclone" and os_is_executable(Path(current)):
            self._binary = current
            return current

        dest = self.get_local_binary_path()
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists() and os_is_executable(dest):
            self._binary = str(dest)
            return str(dest)

        logger.info("Rclone no encontrado. Descargando versión portable...")
        if sys.platform.startswith("win"):
            url = "https://downloads.rclone.org/rclone-current-windows-amd64.zip"
            target_name = "rclone.exe"
        else:
            url = "https://downloads.rclone.org/rclone-current-linux-amd64.zip"
            target_name = "rclone"

        req = urllib.request.urlopen(url, timeout=60)
        zip_data = req.read()
        z = zipfile.ZipFile(io.BytesIO(zip_data))
        for member in z.namelist():
            if member.endswith(f"/{target_name}") or member == target_name:
                dest.write_bytes(z.read(member))
                dest.chmod(dest.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
                logger.info(f"Rclone instalado en {dest}")
                self._binary = str(dest)
                return str(dest)

        return self._binary

    def is_remote_configured(self, remote_name: str = "gdrive") -> bool:
        bin_cmd = self.ensure_rclone_binary()
        try:
            result = subprocess.run(
                [bin_cmd, "listremotes"],
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
        bin_cmd = self.ensure_rclone_binary()
        if self.is_remote_configured(remote_name):
            return [bin_cmd, "config", "reconnect", f"{remote_name}:"]
        return [bin_cmd, "config", "create", remote_name, "drive", "config_is_local=true", "scope=drive"]

    def build_bisync_command(
        self,
        local_path: str,
        remote_folder: str,
        resync: bool = False,
        filters_file: Path | None = None,
    ) -> list[str]:
        bin_cmd = self.ensure_rclone_binary()
        target_filters = filters_file or get_filters_file_path()
        if not target_filters.exists():
            write_filters_file(target_filters)

        clean_remote = remote_folder.strip().strip("/")
        remote_target = f"gdrive:{clean_remote}"
        cmd = [
            bin_cmd,
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
