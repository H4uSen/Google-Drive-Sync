import time
from unittest.mock import MagicMock
from src.core.sync_worker import SyncStatus
from src.tray.tray_icon import TrayManager

def test_tray_notify_on_error():
    worker = MagicMock()
    tray = TrayManager(worker=worker, on_open_gui=MagicMock(), on_exit=MagicMock())
    tray.icon = MagicMock()

    tray.update_status(SyncStatus.ERROR, "Fallo de conexión con Google Drive")
    assert tray.icon.notify.call_count == 1
    call_args = tray.icon.notify.call_args[0]
    assert "Fallo de conexión" in call_args[0]

def test_tray_deduplication_suppresses_repeat_errors():
    worker = MagicMock()
    tray = TrayManager(worker=worker, on_open_gui=MagicMock(), on_exit=MagicMock())
    tray.icon = MagicMock()

    # Primer error: notifica
    tray.update_status(SyncStatus.ERROR, "Fallo de conexión")
    assert tray.icon.notify.call_count == 1

    # Mismo error inmediatamente después: no notifica de nuevo
    tray.update_status(SyncStatus.ERROR, "Fallo de conexión")
    assert tray.icon.notify.call_count == 1

    # Error diferente: notifica
    tray.update_status(SyncStatus.ERROR, "Guardas de seguridad activadas")
    assert tray.icon.notify.call_count == 2

def test_tray_reset_deduplication_on_success():
    worker = MagicMock()
    tray = TrayManager(worker=worker, on_open_gui=MagicMock(), on_exit=MagicMock())
    tray.icon = MagicMock()

    tray.update_status(SyncStatus.ERROR, "Error temporal")
    assert tray.icon.notify.call_count == 1

    # Sincronización exitosa resetea
    tray.update_status(SyncStatus.SUCCESS, "Sincronizado con éxito")

    # Mismo error tras el éxito: debe volver a notificar
    tray.update_status(SyncStatus.ERROR, "Error temporal")
    assert tray.icon.notify.call_count == 2

def test_tray_reset_deduplication_on_idle():
    worker = MagicMock()
    tray = TrayManager(worker=worker, on_open_gui=MagicMock(), on_exit=MagicMock())
    tray.icon = MagicMock()

    tray.update_status(SyncStatus.ERROR, "Error temporal")
    assert tray.icon.notify.call_count == 1

    # Estado IDLE resetea
    tray.update_status(SyncStatus.IDLE, "Inactivo")

    # Mismo error tras idle: debe volver a notificar
    tray.update_status(SyncStatus.ERROR, "Error temporal")
    assert tray.icon.notify.call_count == 2

def test_tray_deduplication_allows_repeat_after_cooldown():
    worker = MagicMock()
    tray = TrayManager(worker=worker, on_open_gui=MagicMock(), on_exit=MagicMock())
    tray.icon = MagicMock()

    tray.update_status(SyncStatus.ERROR, "Fallo de conexión")
    assert tray.icon.notify.call_count == 1

    # Simular paso de 15 minutos (901 segundos)
    tray._last_notification_time -= (tray.COOLDOWN_SECONDS + 1)

    tray.update_status(SyncStatus.ERROR, "Fallo de conexión")
    assert tray.icon.notify.call_count == 2

def test_tray_notify_handles_runtime_exceptions_gracefully():
    worker = MagicMock()
    tray = TrayManager(worker=worker, on_open_gui=MagicMock(), on_exit=MagicMock())
    tray.icon = MagicMock()
    tray.icon.notify.side_effect = RuntimeError("No notification daemon found")

    # No debe propagar la excepción
    tray.update_status(SyncStatus.ERROR, "Fallo de prueba")
    assert tray._last_notified_error == "Fallo de prueba"

def test_tray_notify_method_direct():
    worker = MagicMock()
    tray = TrayManager(worker=worker, on_open_gui=MagicMock(), on_exit=MagicMock())
    tray.icon = MagicMock()

    tray.notify("Obsidian GDrive Sync - Error", "Mensaje detallado")
    tray.icon.notify.assert_called_once_with("Mensaje detallado", "Obsidian GDrive Sync - Error")
