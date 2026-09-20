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

def test_rclone_error_handling_keeps_worker_alive():
    # Review Focus 4: Fallo de red/retorno no-cero pasa a ERROR y no mata el hilo
    cfg = ConfigData(local_vault_path="/fake/vault")
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
