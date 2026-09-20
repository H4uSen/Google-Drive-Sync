"""Tests for TrayManager."""
from PIL import Image
from unittest.mock import MagicMock
from src.tray.tray_icon import TrayManager
from src.core.sync_worker import SyncStatus

def test_create_icon_image():
    mgr = TrayManager(worker=MagicMock(), on_open_gui=MagicMock(), on_exit=MagicMock())
    img = mgr.create_icon_image("#4CAF50")
    assert isinstance(img, Image.Image)
    assert img.size == (64, 64)

def test_tray_menu_actions():
    mock_worker = MagicMock()
    mock_open = MagicMock()
    mock_exit = MagicMock()
    mgr = TrayManager(worker=mock_worker, on_open_gui=mock_open, on_exit=mock_exit)
    menu = mgr._build_menu()
    assert menu is not None

def test_tray_toggle_pause():
    mock_worker = MagicMock()
    mock_worker.status = SyncStatus.IDLE
    mgr = TrayManager(worker=mock_worker, on_open_gui=MagicMock(), on_exit=MagicMock())
    mgr._toggle_pause()
    mock_worker.pause.assert_called_once()
    
    mock_worker.status = SyncStatus.PAUSED
    mgr._toggle_pause()
    mock_worker.resume.assert_called_once()
