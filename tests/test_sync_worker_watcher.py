"""Tests for SyncWorker integration with VaultWatcher."""
from unittest.mock import MagicMock, patch
from src.core.config import ConfigData
from src.core.sync_worker import SyncWorker, SyncStatus


def test_sync_worker_watcher_lifecycle(tmp_path):
    vault = tmp_path / "my_vault"
    vault.mkdir()
    cfg = ConfigData(local_vault_path=str(vault), realtime_sync_enabled=True)
    worker = SyncWorker(config=cfg, rclone_manager=MagicMock())

    with patch("src.core.sync_worker.VaultWatcher") as mock_watcher_cls, patch("subprocess.run"):
        mock_watcher = MagicMock()
        mock_watcher_cls.return_value = mock_watcher

        worker.start()
        assert worker.watcher is not None
        mock_watcher.start.assert_called_once_with(str(vault))

        worker.stop()
        mock_watcher.stop.assert_called_once()
        assert worker.watcher is None


def test_sync_worker_queues_pending_sync_when_busy(tmp_path):
    vault = tmp_path / "my_vault"
    vault.mkdir()
    cfg = ConfigData(local_vault_path=str(vault))
    worker = SyncWorker(config=cfg, rclone_manager=MagicMock())
    worker._running = True

    # Simular estado ocupado
    worker._is_syncing = True
    worker._on_watcher_change()
    assert worker._pending_sync is True

    # Cuando no está ocupado, debe disparar wakeup
    worker._is_syncing = False
    worker._wakeup_event.clear()
    assert not worker._wakeup_event.is_set()
    worker._on_watcher_change()
    assert worker._wakeup_event.is_set()


def test_sync_worker_watcher_ignores_events_when_paused(tmp_path):
    vault = tmp_path / "my_vault"
    vault.mkdir()
    cfg = ConfigData(local_vault_path=str(vault))
    worker = SyncWorker(config=cfg, rclone_manager=MagicMock())
    worker._running = True

    worker.pause()
    worker._on_watcher_change()
    assert worker._pending_sync is False
    assert not worker._wakeup_event.is_set()


def test_sync_worker_watcher_ignores_events_when_not_running(tmp_path):
    vault = tmp_path / "my_vault"
    vault.mkdir()
    cfg = ConfigData(local_vault_path=str(vault))
    worker = SyncWorker(config=cfg, rclone_manager=MagicMock())
    assert not worker._running

    worker._on_watcher_change()
    assert worker._pending_sync is False
    assert not worker._wakeup_event.is_set()


def test_sync_worker_executes_pending_sync_after_finish(tmp_path):
    vault = tmp_path / "my_vault"
    vault.mkdir()
    cfg = ConfigData(local_vault_path=str(vault))
    worker = SyncWorker(config=cfg, rclone_manager=MagicMock())
    worker._pending_sync = True

    with patch("subprocess.run"):
        worker._execute_sync()

    assert worker._pending_sync is False
    assert worker._wakeup_event.is_set()


def test_sync_worker_watcher_not_started_when_disabled(tmp_path):
    vault = tmp_path / "my_vault"
    vault.mkdir()
    cfg = ConfigData(local_vault_path=str(vault), realtime_sync_enabled=False)
    worker = SyncWorker(config=cfg, rclone_manager=MagicMock())

    with patch("src.core.sync_worker.VaultWatcher") as mock_watcher_cls:
        worker.start()
        assert worker.watcher is None
        mock_watcher_cls.assert_not_called()
        worker.stop()


def test_sync_worker_watcher_not_started_without_vault_path():
    cfg = ConfigData(local_vault_path="", realtime_sync_enabled=True)
    worker = SyncWorker(config=cfg, rclone_manager=MagicMock())

    with patch("src.core.sync_worker.VaultWatcher") as mock_watcher_cls:
        worker.start()
        assert worker.watcher is None
        mock_watcher_cls.assert_not_called()
        worker.stop()
