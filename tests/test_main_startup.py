import sys
from unittest.mock import patch, MagicMock
from pathlib import Path

def test_startup_minimized_starts_sync_if_configured():
    with patch("src.main.acquire_single_instance_lock", return_value=True), \
         patch("src.main.release_single_instance_lock"), \
         patch("src.main.ConfigManager"), \
         patch("src.main.RcloneManager"), \
         patch("src.main.SyncWorker"), \
         patch("src.main.TrayManager") as mock_tray_cls, \
         patch("src.main.MainWindow") as mock_window_cls, \
         patch.object(sys, "argv", ["main.py", "--minimized"]):
        
        mock_app = MagicMock()
        mock_app.can_auto_start_sync.return_value = True
        mock_window_cls.return_value = mock_app

        from src.main import main
        mock_app.mainloop.side_effect = None
        main()

        mock_app.withdraw.assert_called_once()
        mock_app.start_sync_engine.assert_called_once()

def test_startup_minimized_notifies_if_not_configured():
    with patch("src.main.acquire_single_instance_lock", return_value=True), \
         patch("src.main.release_single_instance_lock"), \
         patch("src.main.ConfigManager"), \
         patch("src.main.RcloneManager"), \
         patch("src.main.SyncWorker"), \
         patch("src.main.TrayManager") as mock_tray_cls, \
         patch("src.main.MainWindow") as mock_window_cls, \
         patch.object(sys, "argv", ["main.py", "--minimized"]):
        
        mock_app = MagicMock()
        mock_app.can_auto_start_sync.return_value = False
        mock_window_cls.return_value = mock_app

        mock_tray = MagicMock()
        mock_tray_cls.return_value = mock_tray

        from src.main import main
        mock_app.mainloop.side_effect = None
        main()

        mock_app.withdraw.assert_called_once()
        mock_app.start_sync_engine.assert_not_called()
        mock_tray.notify.assert_called_once_with(
            "Obsidian GDrive Sync",
            "Aplicación iniciada en segundo plano. Abre la ventana para configurar tu Vault."
        )

def test_startup_normal_mode_does_not_minimize_or_auto_start():
    with patch("src.main.acquire_single_instance_lock", return_value=True), \
         patch("src.main.release_single_instance_lock"), \
         patch("src.main.ConfigManager"), \
         patch("src.main.RcloneManager"), \
         patch("src.main.SyncWorker"), \
         patch("src.main.TrayManager") as mock_tray_cls, \
         patch("src.main.MainWindow") as mock_window_cls, \
         patch.object(sys, "argv", ["main.py"]):
        
        mock_app = MagicMock()
        mock_app.can_auto_start_sync.return_value = True
        mock_window_cls.return_value = mock_app

        mock_tray = MagicMock()
        mock_tray_cls.return_value = mock_tray

        from src.main import main
        mock_app.mainloop.side_effect = None
        main()

        mock_app.withdraw.assert_not_called()
        mock_app.start_sync_engine.assert_not_called()
        mock_tray.notify.assert_not_called()

def test_can_auto_start_sync_rejects_drive_root():
    from src.gui.app_window import MainWindow

    mock_cfg_mgr = MagicMock()
    mock_rclone = MagicMock()
    mock_rclone.is_remote_configured.return_value = True

    with patch("customtkinter.CTk.__init__", return_value=None):
        win = MainWindow(config_manager=mock_cfg_mgr, worker=MagicMock(), rclone_mgr=mock_rclone)

        mock_resolved = MagicMock()
        mock_resolved.is_dir.return_value = True
        mock_resolved.anchor = "C:\\"
        mock_resolved.resolve.return_value = mock_resolved

        with patch("src.gui.app_window.Path") as mock_path:
            mock_path.side_effect = lambda arg: mock_resolved
            win.cfg.local_vault_path = "C:\\"
            assert win.can_auto_start_sync() is False
