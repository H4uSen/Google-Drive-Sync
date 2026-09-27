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


