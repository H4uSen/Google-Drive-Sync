"""Tests for RcloneManager."""
from pathlib import Path
import pytest
from src.core.rclone_manager import RcloneManager

def test_get_auth_command_not_configured():
    mgr = RcloneManager(rclone_binary="/usr/bin/rclone")
    cmd = mgr.get_auth_command("gdrive")
    assert cmd == [
        "/usr/bin/rclone",
        "config",
        "create",
        "gdrive",
        "drive",
        "config_is_local=true",
        "scope=drive",
        "config_shared_client_id=true",
        "--auto-confirm",
    ]

def test_get_auth_command_reconnect(monkeypatch):
    mgr = RcloneManager(rclone_binary="/usr/bin/rclone")
    monkeypatch.setattr(mgr, "is_remote_configured", lambda name: True)
    cmd = mgr.get_auth_command("gdrive")
    assert cmd == ["/usr/bin/rclone", "config", "reconnect", "gdrive:", "--auto-confirm"]

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

