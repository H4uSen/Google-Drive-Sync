"""
Global test isolation: no test may read or write the user's real
~/.config/obsidian-gdrive-sync (config, history, sync.log) or rclone's
~/.cache/rclone/bisync state, nor see the real rclone 'gdrive' remote.

Set at import time (not in a fixture) because src.main configures the file
logger on import, which happens during test collection.
"""
import os
import tempfile
from pathlib import Path

_base = Path(tempfile.mkdtemp(prefix="ogds-tests-"))
os.environ["XDG_CONFIG_HOME"] = str(_base / "config")
os.environ["XDG_CACHE_HOME"] = str(_base / "cache")
os.environ["APPDATA"] = str(_base / "appdata")
os.environ["RCLONE_CONFIG"] = str(_base / "config" / "rclone" / "rclone.conf")
