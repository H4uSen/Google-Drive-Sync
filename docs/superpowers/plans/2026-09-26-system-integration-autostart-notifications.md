# Integración con el Sistema (Autostart y Notificaciones) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dotar a Obsidian GDrive Sync de inicio automático con el sistema operativo (Linux y Windows) y notificaciones de escritorio nativas ante errores o advertencias críticas con deduplicación anti-spam.

**Architecture:** Módulo utilitario nativo `src/utils/autostart.py` para gestionar entradas `.desktop` (Linux) y Registro HKCU (Windows); extensión de `TrayManager` en `src/tray/tray_icon.py` para emitir notificaciones con cooldown de 15 minutos mediante `pystray.Icon.notify`; integración en `src/gui/app_window.py` mediante un checkbox persistido en `config.json` y auto-arranque del motor en `src/main.py` ante el flag `--minimized`.

**Tech Stack:** Python 3.10+, CustomTkinter, Pystray, winreg (Windows), XDG Autostart spec (Linux), Pytest.

**Spec:** `docs/superpowers/specs/2026-09-26-system-integration-autostart-notifications-design.md`

## Global Constraints

- Plataformas soportadas: Linux y Windows.
- Cero dependencias externas adicionales: usar solo la biblioteca estándar de Python y `pystray` existente.
- Permisos restrictivos: directorios y archivos de autostart creados con modo `0o700`.
- Deduplicación de notificaciones: errores idénticos recurrentes solo se notifican una vez cada 15 minutos (900 segundos).
- Reseteo de errores: una sincronización exitosa (`SyncStatus.SUCCESS` o `SyncStatus.IDLE`) limpia el historial para permitir notificaciones inmediatas ante nuevos problemas.
- Modo silencioso: el flag `--minimized` debe mantener la ventana principal invisible (`withdraw`) e iniciar la sincronización solo si el vault y Google Drive están configurados.

## Review Focus

1. **Ruta con espacios o caracteres especiales en el comando de autostart:** Si la ruta al entorno virtual o proyecto contiene espacios, el archivo `.desktop` y la clave de registro deben entrecomillarse adecuadamente para no fallar en la invocación del SO.
2. **Entornos gráficos sin soporte de notificaciones:** Si `icon.notify` lanza una excepción (ej. en ciertos entornos mínimos de Linux sin demonio de notificaciones), la aplicación debe capturar el error y seguir funcionando sin colapsar el hilo de UI ni el tray.
3. **Persistencia y retrocompatibilidad de configuración:** Si se carga un archivo `config.json` previo sin el campo `autostart_enabled`, debe cargar con el valor por defecto `False` sin corromper la configuración ni fallar.
4. **Idempotencia de activación/desactivación:** Invocar `set_autostart(True)` cuando ya está activo o `set_autostart(False)` cuando no existe archivo/registro debe ejecutarse sin error.
5. **Comportamiento en `--minimized` con configuración incompleta:** Si la app arranca en el inicio del sistema pero el usuario aún no seleccionó vault o no conectó Google Drive, no debe entrar en un bucle continuo de reintentos ni peticiones fallidas a rclone.

---

### Task 1: Modelo de Configuración (`ConfigData.autostart_enabled`)

**Files:**
- Modify: `src/core/config.py:12-25`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: `ConfigData` existente.
- Produces: `ConfigData.autostart_enabled: bool` (default: `False`).

- [ ] **Step 1: Write the failing test**

Añadir en `tests/test_config.py`:
```python
def test_config_autostart_default_and_persistence(tmp_path):
    config_file = tmp_path / "config.json"
    mgr = ConfigManager(config_file=config_file)
    cfg = mgr.load()
    assert cfg.autostart_enabled is False

    cfg.autostart_enabled = True
    mgr.save(cfg)

    loaded = mgr.load()
    assert loaded.autostart_enabled is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_config.py::test_config_autostart_default_and_persistence -v`  
Expected: FAIL con `AttributeError: 'ConfigData' object has no attribute 'autostart_enabled'`

- [ ] **Step 3: Write minimal implementation**

En `src/core/config.py`:
Añadir el atributo `autostart_enabled: bool = False` a `ConfigData`:
```python
@dataclass
class ConfigData:
    local_vault_path: str = ""
    remote_folder_name: str = "ObsidianVault"
    sync_interval_minutes: int = 2
    first_sync_done: bool = False
    last_sync_timestamp: str = ""
    last_sync_status: str = "idle"
    autostart_enabled: bool = False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_config.py -v`  
Expected: PASS en todos los tests de configuración.

- [ ] **Step 5: Commit**

```bash
git add src/core/config.py tests/test_config.py
git commit -m "feat(config): add autostart_enabled field to ConfigData"
```

---

### Task 2: Módulo Utilitario de Autostart (`src/utils/autostart.py`)

**Files:**
- Create: `src/utils/autostart.py`
- Test: `tests/test_autostart.py`

**Interfaces:**
- Consumes: `sys`, `os`, `pathlib.Path`, `src.utils.paths.get_app_dir`.
- Produces:
  - `is_autostart_supported() -> bool`
  - `get_autostart_command() -> str`
  - `set_autostart(enabled: bool) -> bool`
  - `is_autostart_enabled() -> bool`

- [ ] **Step 1: Write the failing tests**

Crear `tests/test_autostart.py`:
```python
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest
from src.utils.autostart import (
    is_autostart_supported,
    get_autostart_command,
    set_autostart,
    is_autostart_enabled,
    get_linux_desktop_file_path,
)

def test_autostart_supported_on_linux_and_windows():
    assert is_autostart_supported() in (True, False)

def test_linux_autostart_command_format():
    cmd = get_autostart_command()
    assert "--minimized" in cmd
    assert "src.main" in cmd

def test_linux_set_autostart_lifecycle(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "linux")
    fake_autostart = tmp_path / "autostart"
    monkeypatch.setattr("src.utils.autostart.get_linux_autostart_dir", lambda: fake_autostart)

    assert is_autostart_enabled() is False

    # Activar
    assert set_autostart(True) is True
    desktop_file = fake_autostart / "obsidian-gdrive-sync.desktop"
    assert desktop_file.exists()
    content = desktop_file.read_text(encoding="utf-8")
    assert "[Desktop Entry]" in content
    assert "--minimized" in content
    assert is_autostart_enabled() is True

    # Idempotencia al activar de nuevo
    assert set_autostart(True) is True
    assert is_autostart_enabled() is True

    # Desactivar
    assert set_autostart(False) is True
    assert not desktop_file.exists()
    assert is_autostart_enabled() is False

    # Idempotencia al desactivar de nuevo
    assert set_autostart(False) is True

def test_windows_set_autostart_lifecycle(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    mock_winreg = MagicMock()
    monkeypatch.setitem(sys.modules, "winreg", mock_winreg)

    # Simular lectura exitosa
    mock_winreg.OpenKey.return_value = MagicMock()
    mock_winreg.QueryValueEx.return_value = ('"pythonw.exe" -m src.main --minimized', 1)

    assert is_autostart_enabled() is True

    # Desactivar
    assert set_autostart(False) is True
    mock_winreg.DeleteValue.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_autostart.py -v`  
Expected: FAIL con `ModuleNotFoundError: No module named 'src.utils.autostart'`

- [ ] **Step 3: Write minimal implementation**

Crear `src/utils/autostart.py`:
```python
import sys
import os
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

APP_NAME = "ObsidianGDriveSync"
DESKTOP_FILENAME = "obsidian-gdrive-sync.desktop"
WIN_REG_SUBKEY = r"Software\Microsoft\Windows\CurrentVersion\Run"

def is_autostart_supported() -> bool:
    return sys.platform.startswith(("linux", "win"))

def get_project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent

def get_linux_autostart_dir() -> Path:
    config_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    autostart_dir = config_home / "autostart"
    autostart_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    return autostart_dir

def get_linux_desktop_file_path() -> Path:
    return get_linux_autostart_dir() / DESKTOP_FILENAME

def get_autostart_command() -> str:
    exe = sys.executable
    if sys.platform.startswith("win"):
        # Buscar pythonw.exe para evitar ventana de consola negra
        pythonw = Path(exe).with_name("pythonw.exe")
        if pythonw.exists():
            exe = str(pythonw)
    return f'"{exe}" -m src.main --minimized'

def set_autostart_linux(enabled: bool) -> bool:
    desktop_file = get_linux_desktop_file_path()
    if enabled:
        project_root = get_project_root()
        cmd = get_autostart_command()
        content = (
            "[Desktop Entry]\n"
            "Type=Application\n"
            f"Name={APP_NAME}\n"
            "Comment=Sincronización continua de Obsidian Vault con Google Drive\n"
            f"Exec={cmd}\n"
            f"Path={project_root}\n"
            "Terminal=false\n"
            "Categories=Utility;Sync;\n"
            "X-GNOME-Autostart-enabled=true\n"
        )
        try:
            desktop_file.write_text(content, encoding="utf-8")
            desktop_file.chmod(0o700)
            return True
        except Exception as e:
            logger.error(f"Error escribiendo archivo autostart Linux: {e}")
            return False
    else:
        try:
            desktop_file.unlink(missing_ok=True)
            return True
        except Exception as e:
            logger.error(f"Error eliminando archivo autostart Linux: {e}")
            return False

def is_autostart_enabled_linux() -> bool:
    return get_linux_desktop_file_path().is_file()

def set_autostart_windows(enabled: bool) -> bool:
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, WIN_REG_SUBKEY, 0, winreg.KEY_SET_VALUE
        )
        with key:
            if enabled:
                cmd = get_autostart_command()
                winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, cmd)
            else:
                try:
                    winreg.DeleteValue(key, APP_NAME)
                except FileNotFoundError:
                    pass
        return True
    except Exception as e:
        logger.error(f"Error modificando clave de registro de autostart en Windows: {e}")
        return False

def is_autostart_enabled_windows() -> bool:
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, WIN_REG_SUBKEY, 0, winreg.KEY_READ
        )
        with key:
            val, _ = winreg.QueryValueEx(key, APP_NAME)
            return bool(val)
    except Exception:
        return False

def set_autostart(enabled: bool) -> bool:
    if sys.platform.startswith("win"):
        return set_autostart_windows(enabled)
    elif sys.platform.startswith("linux"):
        return set_autostart_linux(enabled)
    return False

def is_autostart_enabled() -> bool:
    if sys.platform.startswith("win"):
        return is_autostart_enabled_windows()
    elif sys.platform.startswith("linux"):
        return is_autostart_enabled_linux()
    return False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_autostart.py -v`  
Expected: PASS en todos los casos de prueba de autostart.

- [ ] **Step 5: Commit**

```bash
git add src/utils/autostart.py tests/test_autostart.py
git commit -m "feat(utils): implement autostart module for Linux and Windows"
```

---

### Task 3: Notificaciones y Deduplicación en `TrayManager` (`src/tray/tray_icon.py`)

**Files:**
- Modify: `src/tray/tray_icon.py`
- Test: `tests/test_tray_notifications.py`

**Interfaces:**
- Consumes: `SyncStatus`, `pystray.Icon.notify`.
- Produces:
  - `TrayManager.notify(title: str, message: str) -> None`
  - Control de cooldown (15 minutos) y reseteo en éxito en `TrayManager.update_status(status, msg)`.

- [ ] **Step 1: Write the failing tests**

Crear `tests/test_tray_notifications.py`:
```python
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

def test_tray_notify_handles_runtime_exceptions_gracefully():
    worker = MagicMock()
    tray = TrayManager(worker=worker, on_open_gui=MagicMock(), on_exit=MagicMock())
    tray.icon = MagicMock()
    tray.icon.notify.side_effect = RuntimeError("No notification daemon found")

    # No debe propagar la excepción
    tray.update_status(SyncStatus.ERROR, "Fallo de prueba")
    assert tray._last_notified_error == "Fallo de prueba"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_tray_notifications.py -v`  
Expected: FAIL porque `tray.icon.notify` aún no es llamado en `update_status`.

- [ ] **Step 3: Write minimal implementation**

En `src/tray/tray_icon.py`:
Actualizar la clase `TrayManager` agregando estado de deduplicación y el método `notify`:
```python
import time
# ...
class TrayManager:
    COOLDOWN_SECONDS: float = 900.0  # 15 minutos

    def __init__(
        self,
        worker: SyncWorker,
        on_open_gui: Callable[[], None],
        on_exit: Callable[[], None],
    ):
        self.worker = worker
        self.on_open_gui = on_open_gui
        self.on_exit = on_exit
        self.icon: pystray.Icon | None = None
        self._status_text = "Inactivo"
        self._last_notified_error: str = ""
        self._last_notification_time: float = 0.0

    def notify(self, title: str, message: str):
        if self.icon and hasattr(self.icon, "notify"):
            try:
                self.icon.notify(message, title)
            except Exception as e:
                logger.warning(f"Error mostrando notificación de escritorio: {e}")

    def update_status(self, status: SyncStatus, msg: str):
        self._status_text = msg
        if self.icon:
            try:
                self.icon.icon = self.create_icon_image(status.color)
                self.icon.title = f"Obsidian GDrive Sync: {msg}"
            except Exception as e:
                logger.debug(f"Error updating tray icon: {e}")

        # Lógica de notificaciones con deduplicación y cooldown
        if status == SyncStatus.ERROR:
            now = time.time()
            is_same_error = (msg == self._last_notified_error)
            within_cooldown = (now - self._last_notification_time < self.COOLDOWN_SECONDS)

            if not (is_same_error and within_cooldown):
                self._last_notified_error = msg
                self._last_notification_time = now
                self.notify("Obsidian GDrive Sync - Error", msg)
        elif status in (SyncStatus.SUCCESS, SyncStatus.IDLE):
            self._last_notified_error = ""
            self._last_notification_time = 0.0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_tray_notifications.py tests/test_tray.py -v`  
Expected: PASS en todos los tests de tray y notificaciones.

- [ ] **Step 5: Commit**

```bash
git add src/tray/tray_icon.py tests/test_tray_notifications.py
git commit -m "feat(tray): add desktop notifications with cooldown and anti-spam deduplication"
```

---

### Task 4: Checkbox de Autostart y Refactor en Interfaz Gráfica (`src/gui/app_window.py`)

**Files:**
- Modify: `src/gui/app_window.py`
- Test: `tests/test_gui_state.py`

**Interfaces:**
- Consumes: `src.utils.autostart.set_autostart`, `is_autostart_enabled`.
- Produces:
  - Checkbox en UI para autostart.
  - `MainWindow.can_auto_start_sync() -> bool`
  - `MainWindow.start_sync_engine() -> bool`

- [ ] **Step 1: Write the failing test**

Actualizar `tests/test_gui_state.py`:
```python
from unittest.mock import MagicMock, patch
from src.core.config import ConfigData
from src.gui.app_window import MainWindow

def test_can_auto_start_sync_validation(tmp_path):
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_gui_state.py -v`  
Expected: FAIL con `AttributeError: 'MainWindow' object has no attribute 'can_auto_start_sync'`

- [ ] **Step 3: Write minimal implementation**

En `src/gui/app_window.py`:
1. Importar `autostart` desde `src.utils`:
```python
from src.utils.autostart import set_autostart, is_autostart_enabled
```
2. Añadir el checkbox en `_build_ui` (sección Formulario):
```python
        # Checkbox Iniciar con el sistema
        self.chk_autostart = ctk.CTkCheckBox(
            self.form_frame,
            text="Iniciar automáticamente con el sistema",
            command=self._on_toggle_autostart,
            font=ctk.CTkFont(size=13)
        )
        self.chk_autostart.grid(row=6, column=0, columnspan=2, padx=16, pady=(4, 14), sticky="w")
        if is_autostart_enabled():
            self.chk_autostart.select()
        else:
            self.chk_autostart.deselect()
```
3. Implementar métodos `_on_toggle_autostart`, `can_auto_start_sync` y `start_sync_engine`:
```python
    def _on_toggle_autostart(self):
        enabled = bool(self.chk_autostart.get())
        success = set_autostart(enabled)
        if success:
            self.cfg.autostart_enabled = enabled
            self.config_mgr.save(self.cfg)
            msg = "Inicio automático activado." if enabled else "Inicio automático desactivado."
            self._append_log(msg)
        else:
            self._append_log("⚠ No se pudo actualizar la configuración de inicio automático en el sistema.")
            if is_autostart_enabled():
                self.chk_autostart.select()
            else:
                self.chk_autostart.deselect()

    def can_auto_start_sync(self) -> bool:
        if not self.cfg.local_vault_path:
            return False
        vault_p = Path(self.cfg.local_vault_path).resolve()
        if not vault_p.is_dir() or vault_p == Path(vault_p.root) or vault_p == Path.home():
            return False
        return self.rclone_mgr.is_remote_configured("gdrive")

    def start_sync_engine(self) -> bool:
        if not self.worker._running:
            if not self.can_auto_start_sync():
                return False
            self.worker.start()
            self.btn_toggle_sync.configure(text="Detener Sincronización", fg_color="#C62828", hover_color="#B71C1C")
            self._append_log("Daemon de sincronización iniciado.")
            return True
        return False
```
4. Actualizar `_toggle_sync` para usar `start_sync_engine()`:
```python
    def _toggle_sync(self):
        self._save_form()
        if not self.worker._running:
            if not self.cfg.local_vault_path:
                self._append_log("⚠ Advertencia: Selecciona la ruta local de tu Vault de Obsidian antes de iniciar.")
                return
            vault_p = Path(self.cfg.local_vault_path).resolve()
            if not vault_p.is_dir():
                self._append_log(f"⚠ Error: La carpeta del Vault no existe o no es accesible: {self.cfg.local_vault_path}")
                return
            if vault_p == Path(vault_p.root) or vault_p == Path.home():
                self._append_log("⚠ Error de seguridad: No se permite sincronizar la raíz del sistema o la carpeta de usuario.")
                return
            self.start_sync_engine()
        else:
            self.worker.stop()
            self.btn_toggle_sync.configure(text="Iniciar Sincronización", fg_color="#2E7D32", hover_color="#1B5E20")
            self._append_log("Daemon de sincronización detenido.")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_gui_state.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/gui/app_window.py tests/test_gui_state.py
git commit -m "feat(gui): add autostart checkbox and unified start_sync_engine method"
```

---

### Task 5: Ciclo de Vida y Arranque en Segundo Plano (`src/main.py`)

**Files:**
- Modify: `src/main.py:80-92`
- Test: `tests/test_main_startup.py`

**Interfaces:**
- Consumes: `MainWindow.can_auto_start_sync()`, `MainWindow.start_sync_engine()`, `TrayManager.notify()`.
- Produces: Auto-arranque del motor y gestión de `--minimized` completa.

- [ ] **Step 1: Write the failing test**

Crear `tests/test_main_startup.py`:
```python
import sys
from unittest.mock import patch, MagicMock

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
        # Invocamos main asegurando que app.mainloop finalice de inmediato
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
        main()

        mock_app.withdraw.assert_called_once()
        mock_app.start_sync_engine.assert_not_called()
        mock_tray.notify.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_main_startup.py -v`  
Expected: FAIL porque `src/main.py` todavía no ejecuta `start_sync_engine` ni notifica si no está configurado al recibir `--minimized`.

- [ ] **Step 3: Write minimal implementation**

En `src/main.py`:
Actualizar la lógica posterior a `tray.start()`:
```python
    # Si se pasa --minimized ocultamos la ventana y evaluamos auto-arranque
    if "--minimized" in sys.argv:
        app.withdraw()
        if app.can_auto_start_sync():
            logger.info("Iniciando motor de sincronización automáticamente (--minimized)...")
            app.start_sync_engine()
        else:
            logger.info("Obsidian GDrive Sync iniciado en segundo plano; esperando configuración.")
            tray.notify(
                "Obsidian GDrive Sync",
                "Aplicación iniciada en segundo plano. Abre la ventana para configurar tu Vault."
            )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_main_startup.py tests/test_main_lock.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/main.py tests/test_main_startup.py
git commit -m "feat(main): auto-start sync engine in background when launching with --minimized"
```

---

### Task 6: Verificación Integral y Suite Completa

**Files:**
- Test: Todas las suites de pruebas en `tests/`

- [ ] **Step 1: Run full test suite**

Run: `.venv/bin/pytest tests/ -v`  
Expected: Todos los tests deben pasar (100% PASS), sin regresiones en tests anteriores.

- [ ] **Step 2: Git status and cleanliness check**

Run: `git status -s`  
Expected: Todos los cambios agregados y confirmados en commits atómicos.
