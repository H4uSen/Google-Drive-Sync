"""Tests for single instance locking in main."""
import os
from pathlib import Path
from unittest.mock import patch
from src.main import acquire_single_instance_lock, release_single_instance_lock

def test_acquire_and_release_lock(tmp_path, monkeypatch):
    monkeypatch.setattr("src.main.get_app_dir", lambda: tmp_path)
    assert acquire_single_instance_lock() is True
    lock_file = tmp_path / "app.lock"
    assert lock_file.exists()
    assert lock_file.read_text(encoding="utf-8").strip() == str(os.getpid())
    
    release_single_instance_lock()
    assert not lock_file.exists()

def test_acquire_fails_when_process_is_running(tmp_path, monkeypatch):
    monkeypatch.setattr("src.main.get_app_dir", lambda: tmp_path)
    lock_file = tmp_path / "app.lock"
    lock_file.write_text("99999", encoding="utf-8")
    
    with patch("os.kill", return_value=None):  # Simulated active process
        assert acquire_single_instance_lock() is False

def test_stale_lock_recovered_when_process_dead(tmp_path, monkeypatch):
    monkeypatch.setattr("src.main.get_app_dir", lambda: tmp_path)
    lock_file = tmp_path / "app.lock"
    lock_file.write_text("99999", encoding="utf-8")
    
    def mock_kill(pid, sig):
        raise ProcessLookupError("No such process")
        
    with patch("os.kill", side_effect=mock_kill):
        assert acquire_single_instance_lock() is True
        assert lock_file.read_text(encoding="utf-8").strip() == str(os.getpid())
    
    release_single_instance_lock()

def test_acquire_fails_closed_on_unhandled_error(tmp_path, monkeypatch):
    monkeypatch.setattr("src.main.get_app_dir", lambda: tmp_path)
    with patch("os.open", side_effect=PermissionError("Permission denied")):
        # Fail-closed: should return False, not True
        assert acquire_single_instance_lock() is False

