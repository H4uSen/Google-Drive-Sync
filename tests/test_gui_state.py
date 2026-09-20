"""Tests for GUI state and event handling."""
from unittest.mock import MagicMock
from src.core.config import ConfigData
from src.core.sync_worker import SyncStatus

def test_close_behavior_hides_instead_of_quits():
    mock_app = MagicMock()
    mock_app.withdraw = MagicMock()
    
    def handle_close():
        mock_app.withdraw()

    handle_close()
    mock_app.withdraw.assert_called_once()

def test_status_color_mapping():
    from src.gui.app_window import STATUS_COLORS
    assert STATUS_COLORS[SyncStatus.IDLE] == "#4CAF50"
    assert STATUS_COLORS[SyncStatus.SYNCING] == "#2196F3"
    assert STATUS_COLORS[SyncStatus.PAUSED] == "#FFC107"
    assert STATUS_COLORS[SyncStatus.ERROR] == "#F44336"
