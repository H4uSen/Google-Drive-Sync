"""Tests for RcloneManager."""
from pathlib import Path
import pytest
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
    assert "--tpslimit" in cmd
    assert "8" in cmd
    assert "--max-lock" in cmd
    assert "15m" in cmd
    assert "--color" in cmd
    assert "never" in cmd
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
    assert cmd == ["/usr/bin/rclone", "config", "create", "gdrive", "drive", "config_is_local=true", "scope=drive"]

def test_build_bisync_rejects_empty_or_traversal_remote(tmp_path):
    filter_file = tmp_path / "filters.txt"
    mgr = RcloneManager(rclone_binary="/usr/bin/rclone")
    invalid_remotes = ["", "/", "  ", ".", "..", "../notes", "/nested/../"]
    for remote in invalid_remotes:
        with pytest.raises(ValueError, match="inválida"):
            mgr.build_bisync_command("/home/user/vault", remote, filters_file=filter_file)

def test_build_bisync_rejects_system_root_local(tmp_path):
    filter_file = tmp_path / "filters.txt"
    mgr = RcloneManager(rclone_binary="/usr/bin/rclone")
    with pytest.raises(ValueError, match="raíz"):
        mgr.build_bisync_command("/", "ObsidianVault", filters_file=filter_file)

def test_get_storage_quota_success(monkeypatch):
    import subprocess
    import json
    mgr = RcloneManager(rclone_binary="/usr/bin/rclone")
    fake_json = json.dumps({
        "total": 16106127360,
        "used": 12884901888,
        "trashed": 104857600,
        "free": 3221225472,
    })
    
    def fake_run(cmd, capture_output, text, timeout, check):
        assert cmd == ["/usr/bin/rclone", "about", "gdrive:", "--json"]
        return subprocess.CompletedProcess(cmd, 0, stdout=fake_json)
    
    monkeypatch.setattr(subprocess, "run", fake_run)
    quota = mgr.get_storage_quota("gdrive")
    assert quota is not None
    assert quota["total"] == 16106127360
    assert quota["used"] == 12884901888
    assert "80.0%" in quota["percent_str"] or "80%" in quota["percent_str"]
    assert "GB" in quota["used_str"]
    assert "GB" in quota["total_str"]

def test_get_storage_quota_failure(monkeypatch):
    import subprocess
    mgr = RcloneManager(rclone_binary="/usr/bin/rclone")
    
    def fake_run_err(*args, **kwargs):
        raise subprocess.CalledProcessError(1, ["rclone"])
    
    monkeypatch.setattr(subprocess, "run", fake_run_err)
    assert mgr.get_storage_quota("gdrive") is None

