"""Tests for SyncWorker."""
import pytest
from unittest.mock import MagicMock, patch
from src.core.sync_worker import SyncWorker, SyncStatus
from src.core.config import ConfigData

def test_sync_worker_state_transitions():
    cfg = ConfigData(local_vault_path="/fake/vault", sync_interval_minutes=2)
    worker = SyncWorker(config=cfg, rclone_manager=MagicMock())
    assert worker.status == SyncStatus.IDLE
    worker.pause()
    assert worker.status == SyncStatus.PAUSED
    worker.resume()
    assert worker.status == SyncStatus.IDLE

def test_concurrent_trigger_rejection():
    # Review Focus 5: Llamadas concurrentes a trigger_now no solapan ejecuciones
    cfg = ConfigData(local_vault_path="/fake/vault")
    worker = SyncWorker(config=cfg, rclone_manager=MagicMock())
    worker._is_syncing = True
    result = worker.trigger_now()
    assert result is False

def test_rclone_error_handling_keeps_worker_alive(tmp_path):
    # Review Focus 4: Fallo de red/retorno no-cero pasa a ERROR y no mata el hilo
    vault = tmp_path / "vault"
    vault.mkdir()
    cfg = ConfigData(local_vault_path=str(vault))
    mock_mgr = MagicMock()
    mock_mgr.build_bisync_command.return_value = ["mock_rclone"]
    worker = SyncWorker(config=cfg, rclone_manager=mock_mgr)
    
    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = Exception("Network offline")
        success = worker._execute_sync()
        assert success is False
        assert worker.status == SyncStatus.ERROR
        assert "offline" in worker.last_message.lower()

def test_missing_vault_path_notifies_error():
    cfg = ConfigData(local_vault_path="")
    worker = SyncWorker(config=cfg, rclone_manager=MagicMock())
    success = worker._execute_sync()
    assert success is False
    assert worker.status == SyncStatus.ERROR

def test_nonexistent_vault_path_notifies_error(tmp_path):
    non_existent = str(tmp_path / "non_existent_vault")
    cfg = ConfigData(local_vault_path=non_existent)
    worker = SyncWorker(config=cfg, rclone_manager=MagicMock())
    success = worker._execute_sync()
    assert success is False
    assert worker.status == SyncStatus.ERROR
    assert "no existe" in worker.last_message.lower()

def test_resync_recovery_error_does_not_auto_resync(tmp_path):
    # SEC-01: Must NOT automatically run --resync if safety check trips
    import subprocess
    vault = tmp_path / "vault"
    vault.mkdir()
    cfg = ConfigData(local_vault_path=str(vault))
    mock_mgr = MagicMock()
    mock_mgr.build_bisync_command.return_value = ["mock_rclone"]
    worker = SyncWorker(config=cfg, rclone_manager=mock_mgr)

    err = subprocess.CalledProcessError(
        returncode=2,
        cmd=["mock_rclone"],
        stderr="Critical error: bisync aborted. Too many deletes! Must run --resync to recover",
    )
    with patch("subprocess.run", side_effect=err) as mock_run:
        success = worker._execute_sync()
        assert success is False
        assert worker.status == SyncStatus.ERROR
        assert "resincronización" in worker.last_message.lower() or "resync" in worker.last_message.lower()
        # Verify subprocess.run was only called once and NEVER re-invoked with --resync
        assert mock_run.call_count == 1
        assert mock_mgr.build_bisync_command.call_count == 1

def test_subprocess_timeout_expired_handles_gracefully(tmp_path):
    # SEC-06: Subprocess timeout prevents hung worker
    import subprocess
    vault = tmp_path / "vault"
    vault.mkdir()
    cfg = ConfigData(local_vault_path=str(vault))
    mock_mgr = MagicMock()
    mock_mgr.build_bisync_command.return_value = ["mock_rclone"]
    worker = SyncWorker(config=cfg, rclone_manager=mock_mgr)

    timeout_err = subprocess.TimeoutExpired(cmd=["mock_rclone"], timeout=900)
    with patch("subprocess.run", side_effect=timeout_err):
        success = worker._execute_sync()
        assert success is False
        assert worker.status == SyncStatus.ERROR
        assert "tiempo" in worker.last_message.lower() or "timeout" in worker.last_message.lower()

def test_clean_error_message_strips_ansi():
    from src.core.sync_worker import clean_error_message
    ansi_msg = "\x1b[0m\x1b[91mrclone deletefile \"/some/path.lck\"\x1b[0m"
    result = clean_error_message(ansi_msg)
    assert "\x1b" not in result
    assert "[0m" not in result
    assert "[91m" not in result
    assert "rclone deletefile" in result

def test_try_recover_stale_lock_dead_pid(tmp_path):
    import json
    from src.core.sync_worker import try_recover_stale_lock
    lock_file = tmp_path / "test.lck"
    dead_pid = 99999999
    lock_data = {
        "Session": str(lock_file),
        "PID": str(dead_pid),
        "TimeRenewed": "2026-10-01T00:00:00Z",
        "TimeExpires": "2026-10-01T00:15:00Z",
    }
    lock_file.write_text(json.dumps(lock_data), encoding="utf-8")
    assert lock_file.exists()

    err_text = f"rclone deletefile \"{lock_file}\""
    recovered = try_recover_stale_lock(err_text)
    assert recovered is True
    assert not lock_file.exists()

def test_try_recover_stale_lock_active_pid(tmp_path):
    import os
    import json
    from src.core.sync_worker import try_recover_stale_lock
    lock_file = tmp_path / "test.lck"
    live_pid = os.getpid()
    lock_data = {
        "Session": str(lock_file),
        "PID": str(live_pid),
        "TimeRenewed": "2026-10-01T00:00:00Z",
        "TimeExpires": "2026-10-01T00:15:00Z",
    }
    lock_file.write_text(json.dumps(lock_data), encoding="utf-8")
    assert lock_file.exists()

    err_text = f"lock file already exists: {lock_file}"
    recovered = try_recover_stale_lock(err_text)
    assert recovered is False
    assert lock_file.exists()

def test_execute_sync_auto_recovers_stale_lock(tmp_path):
    import subprocess
    import json
    vault = tmp_path / "vault"
    vault.mkdir()
    lock_file = tmp_path / "stale.lck"
    lock_data = {
        "Session": str(lock_file),
        "PID": "99999999",
    }
    lock_file.write_text(json.dumps(lock_data), encoding="utf-8")

    cfg = ConfigData(local_vault_path=str(vault))
    mock_mgr = MagicMock()
    mock_mgr.build_bisync_command.return_value = ["mock_rclone"]
    worker = SyncWorker(config=cfg, rclone_manager=mock_mgr)

    err = subprocess.CalledProcessError(
        returncode=1,
        cmd=["mock_rclone"],
        stderr=f"ERROR : Bisync critical error: lock file already exists: {lock_file}",
    )

    success_result = MagicMock()
    success_result.returncode = 0

    with patch("subprocess.run", side_effect=[err, success_result]) as mock_run:
        success = worker._execute_sync()
        assert success is True
        assert worker.status == SyncStatus.SUCCESS
        assert not lock_file.exists()
        assert mock_run.call_count == 2



