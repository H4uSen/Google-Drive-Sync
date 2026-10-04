import sys
import os
import shutil
import subprocess
import urllib.request
import zipfile
import stat
import io
import json
import logging
from pathlib import Path
from src.utils.paths import get_filters_file_path, get_app_dir

logger = logging.getLogger(__name__)

def sanitize_remote_folder(remote_folder: str) -> str:
    clean = remote_folder.strip().strip("/\\").replace("\\", "/")
    parts = [p for p in clean.split("/") if p]
    if not clean or clean == "." or ".." in parts:
        raise ValueError("Carpeta remota inválida: no puede ser vacía, raíz o contener '..'")
    return clean

def validate_local_path(local_path: str) -> Path:
    if not local_path or not str(local_path).strip():
        raise ValueError("Ruta local no configurada")
    resolved = Path(str(local_path).strip()).resolve()
    if resolved == Path(resolved.root):
        raise ValueError("Ruta local inválida: no se permite sincronizar la raíz del sistema")
    return resolved

DEFAULT_FILTER_RULES = [
    "- .git/**",
    "- .git",
    "- .gitignore",
    "- .git-credentials",
    "- .obsidian/workspace.json",
    "- .obsidian/workspace-mobile.json",
    "- .obsidian/cache/**",
    "- .obsidian/plugins/obsidian-git/data.json",
    "- .env*",
    "- *.key",
    "- *.pem",
    "- *.tmp",
    "+ *",
]

def write_filters_file(destination_path: Path | None = None) -> Path:
    target = destination_path or get_filters_file_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(DEFAULT_FILTER_RULES) + "\n", encoding="utf-8")
    return target

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
        
        candidates = [
            cls.get_local_binary_path(),
            Path(__file__).resolve().parent.parent.parent / "bin" / ("rclone.exe" if sys.platform.startswith("win") else "rclone"),
        ]
        for path in candidates:
            if path.exists() and os.access(path, os.X_OK):
                return str(path)
            
        return "rclone"

    def ensure_rclone_binary(self) -> str:
        if self._explicit_binary:
            return self._explicit_binary

        current = self.find_rclone_binary()
        if current != "rclone" and os.access(current, os.X_OK):
            self._binary = current
            return current

        dest = self.get_local_binary_path()
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists() and os.access(dest, os.X_OK):
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
        z = zipfile.ZipFile(io.BytesIO(req.read()))
        for member in z.namelist():
            if member.endswith(f"/{target_name}") or member == target_name:
                dest.write_bytes(z.read(member))
                dest.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
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

    def ensure_remote_dir(self, remote_folder: str, remote_name: str = "gdrive") -> bool:
        bin_cmd = self.ensure_rclone_binary()
        clean_remote = sanitize_remote_folder(remote_folder)
        remote_target = f"{remote_name}:{clean_remote}"
        try:
            subprocess.run([bin_cmd, "mkdir", remote_target], capture_output=True, check=True)
            return True
        except Exception as e:
            logger.debug(f"Error ensuring remote dir {remote_target}: {e}")
            return False

    def get_create_command(self, remote_name: str = "gdrive") -> list[str]:
        bin_cmd = self.ensure_rclone_binary()
        return [
            bin_cmd,
            "config",
            "create",
            remote_name,
            "drive",
            "config_is_local=true",
            "scope=drive",
            "config_shared_client_id=true",
            "--auto-confirm",
        ]

    def get_auth_command(self, remote_name: str = "gdrive") -> list[str]:
        bin_cmd = self.ensure_rclone_binary()
        if self.is_remote_configured(remote_name):
            return [bin_cmd, "config", "reconnect", f"{remote_name}:", "--auto-confirm"]
        return self.get_create_command(remote_name)

    def build_bisync_command(
        self,
        local_path: str,
        remote_folder: str,
        resync: bool = False,
        filters_file: Path | None = None,
    ) -> list[str]:
        bin_cmd = self.ensure_rclone_binary()
        validate_local_path(local_path)
        clean_remote = sanitize_remote_folder(remote_folder)

        target_filters = filters_file or get_filters_file_path()
        if not target_filters.exists():
            write_filters_file(target_filters)

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
            "--tpslimit",
            "8",
            "--max-lock",
            "15m",
            "--color",
            "never",
            "--retries",
            "3",
            "-v",
        ]
        if resync:
            cmd.append("--resync")
        return cmd

    def get_storage_quota(self, remote_name: str = "gdrive") -> dict | None:
        bin_cmd = self.ensure_rclone_binary()
        try:
            res = subprocess.run(
                [bin_cmd, "about", f"{remote_name}:", "--json"],
                capture_output=True,
                text=True,
                timeout=15,
                check=True,
            )
            data = json.loads(res.stdout)
            total = data.get("total")
            used = data.get("used", 0)
            free = data.get("free", 0)
            trashed = data.get("trashed", 0)

            def _fmt(b: int | float) -> str:
                if b >= 1024 ** 3:
                    return f"{b / (1024 ** 3):.1f} GB"
                return f"{b / (1024 ** 2):.1f} MB"

            percent = (used / total) if (total and total > 0) else 0.0
            return {
                "total": total,
                "used": used,
                "free": free,
                "trashed": trashed,
                "total_str": _fmt(total) if total else "Ilimitado",
                "used_str": _fmt(used),
                "free_str": _fmt(free),
                "percent": percent,
                "percent_str": f"{percent * 100:.1f}%",
            }
        except Exception as e:
            logger.debug(f"Error fetching storage quota for {remote_name}: {e}")
            return None
