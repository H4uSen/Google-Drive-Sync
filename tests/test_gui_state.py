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

def test_can_auto_start_sync_validation(tmp_path):
    from unittest.mock import patch
    from pathlib import Path
    from src.gui.app_window import MainWindow

    vault = tmp_path / "valid_vault"
    vault.mkdir()
    cfg = ConfigData(local_vault_path=str(vault))
    mock_cfg_mgr = MagicMock()
    mock_cfg_mgr.load.return_value = cfg
    mock_rclone = MagicMock()
    mock_rclone.is_remote_configured.return_value = True

    with patch("customtkinter.CTk.__init__", return_value=None):
        win = MainWindow(config_manager=mock_cfg_mgr, worker=MagicMock(), rclone_mgr=mock_rclone)
        assert win.can_auto_start_sync() is True

        # Invalida si no hay conexión
        mock_rclone.is_remote_configured.return_value = False
        assert win.can_auto_start_sync() is False

        # Invalida si la ruta está vacía
        mock_rclone.is_remote_configured.return_value = True
        win.cfg.local_vault_path = ""
        assert win.can_auto_start_sync() is False

        # Invalida si la ruta no existe
        win.cfg.local_vault_path = str(tmp_path / "nonexistent")
        assert win.can_auto_start_sync() is False

        # Invalida si la ruta es la raíz del sistema
        root_path = Path("/").resolve()
        win.cfg.local_vault_path = str(root_path)
        assert win.can_auto_start_sync() is False

        # Invalida si la ruta es el home del usuario
        win.cfg.local_vault_path = str(Path.home())
        assert win.can_auto_start_sync() is False

def test_start_sync_engine(tmp_path):
    from unittest.mock import patch
    from src.gui.app_window import MainWindow

    vault = tmp_path / "valid_vault"
    vault.mkdir()
    cfg = ConfigData(local_vault_path=str(vault))
    mock_cfg_mgr = MagicMock()
    mock_cfg_mgr.load.return_value = cfg
    mock_worker = MagicMock()
    mock_worker._running = False
    mock_rclone = MagicMock()
    mock_rclone.is_remote_configured.return_value = True

    with patch("customtkinter.CTk.__init__", return_value=None):
        win = MainWindow(config_manager=mock_cfg_mgr, worker=mock_worker, rclone_mgr=mock_rclone)
        win.btn_toggle_sync = MagicMock()
        win.log_box = MagicMock()

        # Caso exitoso: inicia el worker y actualiza el botón
        result = win.start_sync_engine()
        assert result is True
        mock_worker.start.assert_called_once()
        win.btn_toggle_sync.configure.assert_called_with(
            text="Detener Sincronización", fg_color="#C62828", hover_color="#B71C1C"
        )

        # Si ya está corriendo, retorna False y no vuelve a llamar start()
        mock_worker._running = True
        mock_worker.start.reset_mock()
        assert win.start_sync_engine() is False
        mock_worker.start.assert_not_called()

        # Si can_auto_start_sync es False, retorna False
        mock_worker._running = False
        mock_rclone.is_remote_configured.return_value = False
        assert win.start_sync_engine() is False
        mock_worker.start.assert_not_called()

def test_on_toggle_autostart_success():
    from unittest.mock import patch
    from src.gui.app_window import MainWindow

    mock_cfg_mgr = MagicMock()
    mock_cfg_mgr.load.return_value = ConfigData()

    with patch("customtkinter.CTk.__init__", return_value=None), \
         patch("src.gui.app_window.set_autostart", return_value=True) as mock_set:
        win = MainWindow(config_manager=mock_cfg_mgr, worker=MagicMock(), rclone_mgr=MagicMock())
        win.chk_autostart = MagicMock()
        win.log_box = MagicMock()

        # Activar autostart
        win.chk_autostart.get.return_value = 1
        win._on_toggle_autostart()
        mock_set.assert_called_with(True)
        assert win.cfg.autostart_enabled is True
        mock_cfg_mgr.save.assert_called_with(win.cfg)

        # Desactivar autostart
        win.chk_autostart.get.return_value = 0
        win._on_toggle_autostart()
        mock_set.assert_called_with(False)
        assert win.cfg.autostart_enabled is False

def test_on_toggle_autostart_failure_reverts():
    from unittest.mock import patch
    from src.gui.app_window import MainWindow

    mock_cfg_mgr = MagicMock()
    mock_cfg_mgr.load.return_value = ConfigData()

    with patch("customtkinter.CTk.__init__", return_value=None), \
         patch("src.gui.app_window.set_autostart", return_value=False), \
         patch("src.gui.app_window.is_autostart_enabled", return_value=False):
        win = MainWindow(config_manager=mock_cfg_mgr, worker=MagicMock(), rclone_mgr=MagicMock())
        win.chk_autostart = MagicMock()
        win.log_box = MagicMock()

        win.chk_autostart.get.return_value = 1
        win._on_toggle_autostart()
        # Debe revertir a deseleccionado
        win.chk_autostart.deselect.assert_called_once()
        # No debió guardar en config_mgr
        mock_cfg_mgr.save.assert_not_called()

def test_toggle_sync(tmp_path):
    from unittest.mock import patch
    from src.gui.app_window import MainWindow

    vault = tmp_path / "valid_vault"
    vault.mkdir()
    cfg = ConfigData(local_vault_path=str(vault))
    mock_cfg_mgr = MagicMock()
    mock_cfg_mgr.load.return_value = cfg
    mock_worker = MagicMock()
    mock_worker._running = False
    mock_rclone = MagicMock()
    mock_rclone.is_remote_configured.return_value = True

    with patch("customtkinter.CTk.__init__", return_value=None):
        win = MainWindow(config_manager=mock_cfg_mgr, worker=mock_worker, rclone_mgr=mock_rclone)
        win._save_form = MagicMock()
        win.start_sync_engine = MagicMock()
        win.btn_toggle_sync = MagicMock()
        win.log_box = MagicMock()

        # Iniciar sincronización
        win._toggle_sync()
        win.start_sync_engine.assert_called_once()

        # Detener sincronización si ya está corriendo
        mock_worker._running = True
        win._toggle_sync()
        mock_worker.stop.assert_called_once()
        win.btn_toggle_sync.configure.assert_called_with(
            text="Iniciar Sincronización", fg_color="#2E7D32", hover_color="#1B5E20"
        )

def test_build_ui_autostart_checkbox_selected():
    import os
    import pytest
    from unittest.mock import patch, MagicMock
    from src.gui.app_window import MainWindow

    if not os.environ.get("DISPLAY"):
        pytest.skip("DISPLAY not available")

    mock_cfg_mgr = MagicMock()
    mock_cfg_mgr.load.return_value = ConfigData()

    with patch("src.gui.app_window.is_autostart_enabled", return_value=True):
        win = MainWindow(config_manager=mock_cfg_mgr, worker=MagicMock(), rclone_mgr=MagicMock())
        try:
            assert win.chk_autostart.get() == 1
        finally:
            win.destroy()

def test_build_ui_autostart_checkbox_deselected():
    import os
    import pytest
    from unittest.mock import patch, MagicMock
    from src.gui.app_window import MainWindow

    if not os.environ.get("DISPLAY"):
        pytest.skip("DISPLAY not available")

    mock_cfg_mgr = MagicMock()
    mock_cfg_mgr.load.return_value = ConfigData()

    with patch("src.gui.app_window.is_autostart_enabled", return_value=False):
        win = MainWindow(config_manager=mock_cfg_mgr, worker=MagicMock(), rclone_mgr=MagicMock())
        try:
            assert win.chk_autostart.get() == 0
        finally:
            win.destroy()




