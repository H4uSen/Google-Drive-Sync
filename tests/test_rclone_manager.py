"""Tests for RcloneManager."""
from pathlib import Path
from src.core.rclone_manager import RcloneManager

def test_build_bisync_command_basic(tmp_path):
    filter_file = tmp_path / "filters.txt"
    mgr = RcloneManager(rclone_binary="/usr/bin/rclone")
    cmd = mgr.build_bisync_command(
        "/home/user/vault", "ObsidianVault", resync=False, filters_file=filter_file
    )
    assert cmd[0] == "/usr/bin/rclone"
    assert "bisync" in cmd
    assert "/home/user/vault" in cmd
    assert "gdrive:ObsidianVault" in cmd
    assert "--conflict-resolve" in cmd
    assert "none" in cmd
    assert "--conflict-loser" in cmd
    assert "pathname" in cmd
    assert "--resync" not in cmd

def test_build_bisync_command_resync(tmp_path):
    filter_file = tmp_path / "filters.txt"
    mgr = RcloneManager(rclone_binary="/usr/bin/rclone")
    cmd = mgr.build_bisync_command(
        "/home/user/vault", "ObsidianVault", resync=True, filters_file=filter_file
    )
    assert "--resync" in cmd

def test_build_bisync_command_with_spaces_in_path(tmp_path):
    # Review Focus 3: Rutas con espacios
    filter_file = tmp_path / "filters.txt"
    mgr = RcloneManager(rclone_binary="/usr/bin/rclone")
    local_with_spaces = "/home/user/My Obsidian Vault"
    cmd = mgr.build_bisync_command(
        local_with_spaces, "My Remote Vault", filters_file=filter_file
    )
    assert local_with_spaces in cmd
    assert "gdrive:My Remote Vault" in cmd

def test_get_auth_command():
    mgr = RcloneManager(rclone_binary="/usr/bin/rclone")
    cmd = mgr.get_auth_command("gdrive")
    assert cmd == ["/usr/bin/rclone", "config", "create", "gdrive", "drive", "scope=drive"]
