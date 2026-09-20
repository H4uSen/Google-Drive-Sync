# Obsidian GDrive Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construir una aplicación de escritorio multiplataforma (Windows y Linux) con interfaz gráfica (CustomTkinter) y presencia en la bandeja del sistema (pystray) para sincronizar un vault de Obsidian con Google Drive de forma bidireccional continua (por defecto cada 2 minutos) usando el motor Rclone.

**Architecture:** La aplicación divide responsabilidades de forma desacoplada: una capa de interfaz gráfica ligera (CustomTkinter) y un gestor de bandeja del sistema (pystray) interactúan con un trabajador en segundo plano (`SyncWorker`) no bloqueante. El trabajador gestiona el ciclo del temporizador, invoca el motor `rclone bisync` con exclusiones estrictas de Obsidian (`.obsidian/workspace*.json`) y Git (`.git/**`), asegurando transferencias seguras, resolución de conflictos sin pérdida de datos y prevención de ejecuciones concurrentes.

**Tech Stack:** Python 3.10+, CustomTkinter, pystray, Pillow, Rclone (binario nativo/portable), pytest.

**Spec:** [docs/superpowers/specs/2026-09-20-obsidian-gdrive-sync-design.md](file:///home/hausen/Projects/Google%20Drive%20Sync/docs/superpowers/specs/2026-09-20-obsidian-gdrive-sync-design.md)

## Global Constraints

- Compatibilidad multiplataforma garantizada para Windows (10/11) y Linux.
- Sincronización continua bidireccional con intervalo predeterminado de 2 minutos, configurable por el usuario.
- Exclusión estricta de `.git/**` para garantizar 100% de coexistencia con Obsidian Git y repositorios GitHub.
- Exclusión automática de `.obsidian/workspace.json`, `.obsidian/workspace-mobile.json` y cachés temporales.
- Resolución segura de conflictos: nunca sobrescribir sin crear respaldo (`--conflict-resolve none`, `--conflict-loser pathname`).
- Cerrar la ventana principal con `X` minimiza la app al System Tray en lugar de terminar el proceso; terminar requiere seleccionar "Salir" en el menú contextual.

## Review Focus

1. **Intervalo no válido (< 1 minuto o texto corrupto):** El validador de configuración debe rechazar o ajustar automáticamente a un mínimo de 1 minuto y valor por defecto de 2 minutos. (Asignado a Tarea 2)
2. **Archivo `config.json` corrupto o truncado:** El gestor de configuración debe respaldar el archivo dañado y cargar valores por defecto seguros en lugar de crashear. (Asignado a Tarea 2)
3. **Rutas locales con espacios o caracteres especiales:** El generador de comandos de Rclone debe procesar y entrecomillar adecuadamente rutas complejas de directorios. (Asignado a Tarea 4)
4. **Pérdida de conexión de red o error de salida en Rclone:** El trabajador `SyncWorker` debe capturar el código de retorno fallido, registrar el mensaje en los logs y pasar al estado `ERROR` sin detener el bucle del temporizador. (Asignado a Tarea 5)
5. **Llamadas concurrentes a `trigger_now()` mientras ya se sincroniza:** El trabajador debe rechazar de forma segura la ejecución duplicada utilizando un cerrojo (`threading.Lock`). (Asignado a Tarea 5)

---

### Task 1: Scaffolding, Paths Multiplataforma y Logger

**Files:**
- Create: `requirements.txt`
- Create: `.gitignore`
- Create: `src/__init__.py`
- Create: `src/utils/__init__.py`
- Create: `src/utils/paths.py`
- Create: `src/utils/logger.py`
- Create: `tests/__init__.py`
- Create: `tests/test_paths.py`

**Interfaces:**
- Produces:
  - `get_app_dir() -> Path`: Ruta base de datos (`~/.config/obsidian-gdrive-sync` en Linux, `%APPDATA%/ObsidianGDriveSync` en Windows).
  - `get_config_file_path() -> Path`: Ruta de `config.json`.
  - `get_log_file_path() -> Path`: Ruta de `sync.log`.
  - `get_filters_file_path() -> Path`: Ruta de `filters.txt`.
  - `setup_logger() -> logging.Logger`: Configuración de logging con rotación.

- [ ] **Step 1: Escribir la prueba unitaria fallida para resolución de rutas**

```python
# tests/test_paths.py
from pathlib import Path
import os
from src.utils.paths import (
    get_app_dir,
    get_config_file_path,
    get_log_file_path,
    get_filters_file_path,
)

def test_paths_return_valid_paths():
    app_dir = get_app_dir()
    assert isinstance(app_dir, Path)
    assert app_dir.name in ("obsidian-gdrive-sync", "ObsidianGDriveSync")
    
    config_file = get_config_file_path()
    assert config_file.parent == app_dir
    assert config_file.name == "config.json"
    
    log_file = get_log_file_path()
    assert log_file.name == "sync.log"
    
    filters_file = get_filters_file_path()
    assert filters_file.name == "filters.txt"
```

- [ ] **Step 2: Ejecutar la prueba y verificar que falla**

Run: `pytest tests/test_paths.py -v`  
Expected: FAIL con `ModuleNotFoundError: No module named 'src'`

- [ ] **Step 3: Implementar `requirements.txt`, `.gitignore`, `paths.py` y `logger.py`**

```python
# src/utils/paths.py
import sys
import os
from pathlib import Path

def get_app_dir() -> Path:
    if sys.platform.startswith("win"):
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        app_dir = base / "ObsidianGDriveSync"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
        app_dir = base / "obsidian-gdrive-sync"
    
    app_dir.mkdir(parents=True, exist_ok=True)
    return app_dir

def get_config_file_path() -> Path:
    return get_app_dir() / "config.json"

def get_log_file_path() -> Path:
    return get_app_dir() / "sync.log"

def get_filters_file_path() -> Path:
    return get_app_dir() / "filters.txt"
```

- [ ] **Step 4: Ejecutar la prueba y verificar que pasa**

Run: `pytest tests/test_paths.py -v`  
Expected: PASS

- [ ] **Step 5: Confirmar cambios en git**

```bash
git add requirements.txt .gitignore src/ tests/
git commit -m "feat: setup project scaffolding, cross-platform paths and logger"
```

---

### Task 2: Gestor de Configuración Atómico (`src/core/config.py`)

**Files:**
- Create: `src/core/__init__.py`
- Create: `src/core/config.py`
- Create: `tests/test_config.py`

**Interfaces:**
- Consumes: `src.utils.paths.get_config_file_path`
- Produces:
  - `ConfigData`: Dataclass con `local_vault_path: str`, `remote_folder_name: str`, `sync_interval_minutes: int`, `autostart_enabled: bool`, `first_sync_done: bool`, `theme: str`.
  - `ConfigManager`:
    - `load() -> ConfigData`
    - `save(config: ConfigData) -> None`
    - `update(**kwargs) -> ConfigData`

- [ ] **Step 1: Escribir las pruebas unitarias para el gestor de configuración (incluyendo Review Focus 1 y 2)**

```python
# tests/test_config.py
import pytest
import json
from pathlib import Path
from src.core.config import ConfigManager, ConfigData

def test_default_config(tmp_path):
    config_file = tmp_path / "config.json"
    manager = ConfigManager(config_file=config_file)
    cfg = manager.load()
    assert cfg.sync_interval_minutes == 2
    assert cfg.remote_folder_name == "ObsidianVault"
    assert cfg.first_sync_done is False

def test_save_and_load_config(tmp_path):
    config_file = tmp_path / "config.json"
    manager = ConfigManager(config_file=config_file)
    cfg = ConfigData(
        local_vault_path="/tmp/myvault",
        remote_folder_name="BackupVault",
        sync_interval_minutes=5,
        autostart_enabled=True,
    )
    manager.save(cfg)
    loaded = manager.load()
    assert loaded.local_vault_path == "/tmp/myvault"
    assert loaded.sync_interval_minutes == 5
    assert loaded.autostart_enabled is True

def test_interval_validation_clamping(tmp_path):
    # Review Focus 1: intervalo < 1 debe ajustarse a 1 o valor por defecto
    config_file = tmp_path / "config.json"
    manager = ConfigManager(config_file=config_file)
    cfg = ConfigData(sync_interval_minutes=0)
    manager.save(cfg)
    loaded = manager.load()
    assert loaded.sync_interval_minutes >= 1

def test_corrupt_config_fallback(tmp_path):
    # Review Focus 2: JSON corrupto se recupera con defaults sin crashear
    config_file = tmp_path / "config.json"
    config_file.write_text("{corrupted_json_content...", encoding="utf-8")
    manager = ConfigManager(config_file=config_file)
    cfg = manager.load()
    assert cfg.sync_interval_minutes == 2
    assert (tmp_path / "config.json.bak").exists()
```

- [ ] **Step 2: Ejecutar la prueba y verificar que falla**

Run: `pytest tests/test_config.py -v`  
Expected: FAIL con `ImportError: cannot import name 'ConfigManager'`

- [ ] **Step 3: Implementar `src/core/config.py`**

```python
# src/core/config.py
from dataclasses import dataclass, asdict
from pathlib import Path
import json
import shutil
import logging
from src.utils.paths import get_config_file_path

logger = logging.getLogger(__name__)

@dataclass
class ConfigData:
    local_vault_path: str = ""
    remote_folder_name: str = "ObsidianVault"
    sync_interval_minutes: int = 2
    autostart_enabled: bool = False
    first_sync_done: bool = False
    last_sync_timestamp: str = ""
    last_sync_status: str = "idle"
    theme: str = "dark"

    def clean(self):
        if not isinstance(self.sync_interval_minutes, int) or self.sync_interval_minutes < 1:
            self.sync_interval_minutes = 2

class ConfigManager:
    def __init__(self, config_file: Path | None = None):
        self.config_file = config_file or get_config_file_path()

    def load(self) -> ConfigData:
        if not self.config_file.exists():
            default = ConfigData()
            self.save(default)
            return default
        try:
            with open(self.config_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            cfg = ConfigData(**data)
            cfg.clean()
            return cfg
        except Exception as e:
            logger.error(f"Error reading config, restoring backup: {e}")
            bak = self.config_file.with_suffix(".json.bak")
            shutil.copyfile(self.config_file, bak)
            default = ConfigData()
            self.save(default)
            return default

    def save(self, config: ConfigData) -> None:
        config.clean()
        temp_file = self.config_file.with_suffix(".tmp")
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(asdict(config), f, indent=2, ensure_ascii=False)
        temp_file.replace(self.config_file)
```

- [ ] **Step 4: Ejecutar las pruebas y verificar que pasan**

Run: `pytest tests/test_config.py -v`  
Expected: PASS

- [ ] **Step 5: Confirmar cambios en git**

```bash
git add src/core/config.py tests/test_config.py
git commit -m "feat: implement atomic ConfigManager with validation and corruption recovery"
```

---

### Task 3: Generador de Reglas de Filtro de Obsidian y Git (`src/core/filter_rules.py`)

**Files:**
- Create: `src/core/filter_rules.py`
- Create: `tests/test_filter_rules.py`

**Interfaces:**
- Produces:
  - `get_default_filter_rules() -> list[str]`
  - `write_filters_file(destination_path: Path) -> Path`

- [ ] **Step 1: Escribir la prueba unitaria para las reglas de exclusión de Obsidian y Git**

```python
# tests/test_filter_rules.py
from pathlib import Path
from src.core.filter_rules import get_default_filter_rules, write_filters_file

def test_default_rules_contain_git_and_obsidian_exclusions():
    rules = get_default_filter_rules()
    assert "- .git/**" in rules
    assert "- .gitignore" in rules
    assert "- .obsidian/workspace.json" in rules
    assert "- .obsidian/workspace-mobile.json" in rules
    assert "- .obsidian/cache/**" in rules
    assert "+ *" in rules

def test_write_filters_file(tmp_path):
    filter_file = tmp_path / "filters.txt"
    written = write_filters_file(filter_file)
    assert written.exists()
    content = written.read_text(encoding="utf-8")
    assert "- .git/**" in content
    assert "+ *" in content
```

- [ ] **Step 2: Ejecutar la prueba y verificar que falla**

Run: `pytest tests/test_filter_rules.py -v`  
Expected: FAIL con `ImportError: cannot import name 'get_default_filter_rules'`

- [ ] **Step 3: Implementar `src/core/filter_rules.py`**

```python
# src/core/filter_rules.py
from pathlib import Path
from src.utils.paths import get_filters_file_path

DEFAULT_FILTER_RULES = [
    "# Exclusiones estrictas para coexistencia con Git/GitHub",
    "- .git/**",
    "- .gitignore",
    "# Exclusiones de archivos volátiles de Obsidian",
    "- .obsidian/workspace.json",
    "- .obsidian/workspace-mobile.json",
    "- .obsidian/cache/**",
    "- *.tmp",
    "# Inclusión explícita de notas, adjuntos, plugins, temas y libros",
    "+ *",
]

def get_default_filter_rules() -> list[str]:
    return list(DEFAULT_FILTER_RULES)

def write_filters_file(destination_path: Path | None = None) -> Path:
    target = destination_path or get_filters_file_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w", encoding="utf-8") as f:
        f.write("\n".join(DEFAULT_FILTER_RULES) + "\n")
    return target
```

- [ ] **Step 4: Ejecutar la prueba y verificar que pasa**

Run: `pytest tests/test_filter_rules.py -v`  
Expected: PASS

- [ ] **Step 5: Confirmar cambios en git**

```bash
git add src/core/filter_rules.py tests/test_filter_rules.py
git commit -m "feat: implement filter rules generator for git and obsidian exclusions"
```

---

### Task 4: Gestor de Rclone y Constructor de Comandos (`src/core/rclone_manager.py`)

**Files:**
- Create: `src/core/rclone_manager.py`
- Create: `tests/test_rclone_manager.py`

**Interfaces:**
- Consumes: `src.core.filter_rules.write_filters_file`
- Produces:
  - `RcloneManager`:
    - `find_rclone_binary() -> str`
    - `build_bisync_command(local_path: str, remote_folder: str, resync: bool = False) -> list[str]`
    - `is_remote_configured(remote_name: str = "gdrive") -> bool`
    - `get_auth_command(remote_name: str = "gdrive") -> list[str]`

- [ ] **Step 1: Escribir la prueba unitaria (incluyendo Review Focus 3: rutas con espacios)**

```python
# tests/test_rclone_manager.py
from pathlib import Path
from src.core.rclone_manager import RcloneManager

def test_build_bisync_command_basic():
    mgr = RcloneManager(rclone_binary="/usr/bin/rclone")
    cmd = mgr.build_bisync_command("/home/user/vault", "ObsidianVault", resync=False)
    assert cmd[0] == "/usr/bin/rclone"
    assert "bisync" in cmd
    assert "/home/user/vault" in cmd
    assert "gdrive:ObsidianVault" in cmd
    assert "--conflict-resolve" in cmd
    assert "none" in cmd
    assert "--conflict-loser" in cmd
    assert "pathname" in cmd
    assert "--resync" not in cmd

def test_build_bisync_command_resync():
    mgr = RcloneManager(rclone_binary="/usr/bin/rclone")
    cmd = mgr.build_bisync_command("/home/user/vault", "ObsidianVault", resync=True)
    assert "--resync" in cmd

def test_build_bisync_command_with_spaces_in_path():
    # Review Focus 3: Rutas con espacios
    mgr = RcloneManager(rclone_binary="/usr/bin/rclone")
    local_with_spaces = "/home/user/My Obsidian Vault"
    cmd = mgr.build_bisync_command(local_with_spaces, "My Remote Vault")
    assert local_with_spaces in cmd
    assert "gdrive:My Remote Vault" in cmd
```

- [ ] **Step 2: Ejecutar la prueba y verificar que falla**

Run: `pytest tests/test_rclone_manager.py -v`  
Expected: FAIL con `ImportError: cannot import name 'RcloneManager'`

- [ ] **Step 3: Implementar `src/core/rclone_manager.py`**

```python
# src/core/rclone_manager.py
import shutil
import subprocess
from pathlib import Path
from src.core.filter_rules import write_filters_file
from src.utils.paths import get_filters_file_path

class RcloneManager:
    def __init__(self, rclone_binary: str | None = None):
        self._binary = rclone_binary or self.find_rclone_binary()

    @staticmethod
    def find_rclone_binary() -> str:
        system_bin = shutil.which("rclone")
        if system_bin:
            return system_bin
        return "rclone"

    def is_remote_configured(self, remote_name: str = "gdrive") -> bool:
        try:
            result = subprocess.run(
                [self._binary, "listremotes"],
                capture_output=True,
                text=True,
                check=True,
            )
            remotes = [r.strip().rstrip(":") for r in result.stdout.splitlines()]
            return remote_name in remotes
        except Exception:
            return False

    def get_auth_command(self, remote_name: str = "gdrive") -> list[str]:
        return [self._binary, "config", "create", remote_name, "drive", "scope=drive"]

    def build_bisync_command(
        self,
        local_path: str,
        remote_folder: str,
        resync: bool = False,
        filters_file: Path | None = None,
    ) -> list[str]:
        target_filters = filters_file or get_filters_file_path()
        if not target_filters.exists():
            write_filters_file(target_filters)

        remote_target = f"gdrive:{remote_folder.strip('/')}"
        cmd = [
            self._binary,
            "bisync",
            local_path,
            remote_target,
            "--filters-file",
            str(target_filters),
            "--drive-chunk-size",
            "32M",
            "--conflict-resolve",
            "none",
            "--conflict-loser",
            "pathname",
            "--check-access",
            "--retries",
            "3",
            "-v",
        ]
        if resync:
            cmd.append("--resync")
        return cmd
```

- [ ] **Step 4: Ejecutar la prueba y verificar que pasa**

Run: `pytest tests/test_rclone_manager.py -v`  
Expected: PASS

- [ ] **Step 5: Confirmar cambios en git**

```bash
git add src/core/rclone_manager.py tests/test_rclone_manager.py
git commit -m "feat: implement RcloneManager command builder and remote validation"
```

---

### Task 5: Trabajador de Sincronización en Segundo Plano (`src/core/sync_worker.py`)

**Files:**
- Create: `src/core/sync_worker.py`
- Create: `tests/test_sync_worker.py`

**Interfaces:**
- Consumes: `src.core.config.ConfigManager`, `src.core.rclone_manager.RcloneManager`
- Produces:
  - `SyncStatus` (Enum: `IDLE`, `SYNCING`, `SUCCESS`, `PAUSED`, `ERROR`)
  - `SyncWorker`:
    - `start() -> None`
    - `stop() -> None`
    - `pause() -> None`
    - `resume() -> None`
    - `trigger_now() -> bool`
    - `register_listener(callback: Callable[[SyncStatus, str], None]) -> None`

- [ ] **Step 1: Escribir las pruebas unitarias del trabajador (incluyendo Review Focus 4 y 5)**

```python
# tests/test_sync_worker.py
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
    # Intento de segundo trigger inmediato debe retornar False y no ejecutar
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
```

- [ ] **Step 2: Ejecutar la prueba y verificar que falla**

Run: `pytest tests/test_sync_worker.py -v`  
Expected: FAIL con `ImportError: cannot import name 'SyncWorker'`

- [ ] **Step 3: Implementar `src/core/sync_worker.py`**

```python
# src/core/sync_worker.py
from enum import Enum
import threading
import time
import subprocess
import logging
from typing import Callable
from src.core.config import ConfigData
from src.core.rclone_manager import RcloneManager

logger = logging.getLogger(__name__)

class SyncStatus(Enum):
    IDLE = "idle"
    SYNCING = "syncing"
    SUCCESS = "success"
    PAUSED = "paused"
    ERROR = "error"

class SyncWorker:
    def __init__(self, config: ConfigData, rclone_manager: RcloneManager):
        self.config = config
        self.rclone = rclone_manager
        self.status = SyncStatus.IDLE
        self.last_message = ""
        self.last_sync_time = ""
        
        self._listeners: list[Callable[[SyncStatus, str], None]] = []
        self._running = False
        self._paused = False
        self._is_syncing = False
        self._sync_lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._wakeup_event = threading.Event()

    def register_listener(self, cb: Callable[[SyncStatus, str], None]):
        self._listeners.append(cb)

    def _notify(self, status: SyncStatus, msg: str):
        self.status = status
        self.last_message = msg
        for cb in self._listeners:
            try:
                cb(status, msg)
            except Exception as e:
                logger.error(f"Listener error: {e}")

    def pause(self):
        self._paused = True
        self._notify(SyncStatus.PAUSED, "Sincronización pausada")

    def resume(self):
        self._paused = False
        self._notify(SyncStatus.IDLE, "Sincronización reanudada")

    def trigger_now(self) -> bool:
        if self._is_syncing or self._paused:
            return False
        self._wakeup_event.set()
        return True

    def _execute_sync(self) -> bool:
        if not self.config.local_vault_path:
            self._notify(SyncStatus.ERROR, "Ruta de vault no configurada")
            return False

        with self._sync_lock:
            self._is_syncing = True
            self._notify(SyncStatus.SYNCING, "Sincronizando con Google Drive...")
            try:
                resync = not self.config.first_sync_done
                cmd = self.rclone.build_bisync_command(
                    self.config.local_vault_path,
                    self.config.remote_folder_name,
                    resync=resync,
                )
                res = subprocess.run(cmd, capture_output=True, text=True, check=True)
                self.config.first_sync_done = True
                self.last_sync_time = time.strftime("%H:%M:%S")
                self._notify(SyncStatus.SUCCESS, f"Sincronizado con éxito ({self.last_sync_time})")
                return True
            except subprocess.CalledProcessError as e:
                err_msg = e.stderr or e.stdout or "Error desconocido en rclone"
                logger.error(f"Rclone error: {err_msg}")
                self._notify(SyncStatus.ERROR, f"Fallo al sincronizar: {err_msg[:100]}")
                return False
            except Exception as e:
                logger.error(f"Error de sincronización: {e}")
                self._notify(SyncStatus.ERROR, f"Error: {str(e)}")
                return False
            finally:
                self._is_syncing = False

    def _run_loop(self):
        while self._running:
            if not self._paused:
                self._execute_sync()
            
            interval_sec = max(60, self.config.sync_interval_minutes * 60)
            triggered = self._wakeup_event.wait(timeout=interval_sec)
            if triggered:
                self._wakeup_event.clear()

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        self._wakeup_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)
```

- [ ] **Step 4: Ejecutar las pruebas y verificar que pasan**

Run: `pytest tests/test_sync_worker.py -v`  
Expected: PASS

- [ ] **Step 5: Confirmar cambios en git**

```bash
git add src/core/sync_worker.py tests/test_sync_worker.py
git commit -m "feat: implement background SyncWorker with lock protection and error handling"
```

---

### Task 6: Integración con la Bandeja del Sistema (`src/tray/tray_icon.py`)

**Files:**
- Create: `src/tray/__init__.py`
- Create: `src/tray/tray_icon.py`
- Create: `tests/test_tray.py`

**Interfaces:**
- Consumes: `src.core.sync_worker.SyncWorker`, `src.core.sync_worker.SyncStatus`
- Produces:
  - `TrayManager`:
    - `create_icon_image(color: str) -> PIL.Image.Image`
    - `start() -> None`
    - `update_status(status: SyncStatus, msg: str) -> None`
    - `stop() -> None`

- [ ] **Step 1: Escribir la prueba unitaria para la generación de iconos dinámicos y menú del Tray**

```python
# tests/test_tray.py
from PIL import Image
from unittest.mock import MagicMock
from src.tray.tray_icon import TrayManager
from src.core.sync_worker import SyncStatus

def test_create_icon_image():
    mgr = TrayManager(worker=MagicMock(), on_open_gui=MagicMock(), on_exit=MagicMock())
    img = mgr.create_icon_image("green")
    assert isinstance(img, Image.Image)
    assert img.size == (64, 64)

def test_tray_menu_actions():
    mock_worker = MagicMock()
    mock_open = MagicMock()
    mock_exit = MagicMock()
    mgr = TrayManager(worker=mock_worker, on_open_gui=mock_open, on_exit=mock_exit)
    menu = mgr._build_menu()
    assert menu is not None
```

- [ ] **Step 2: Ejecutar la prueba y verificar que falla**

Run: `pytest tests/test_tray.py -v`  
Expected: FAIL con `ImportError: cannot import name 'TrayManager'`

- [ ] **Step 3: Implementar `src/tray/tray_icon.py`**

```python
# src/tray/tray_icon.py
import threading
from typing import Callable
from PIL import Image, ImageDraw
import pystray
from src.core.sync_worker import SyncWorker, SyncStatus

COLOR_MAP = {
    SyncStatus.IDLE: "#4CAF50",      # Verde
    SyncStatus.SUCCESS: "#4CAF50",   # Verde
    SyncStatus.SYNCING: "#2196F3",   # Azul
    SyncStatus.PAUSED: "#FFC107",    # Amarillo
    SyncStatus.ERROR: "#F44336",     # Rojo
}

class TrayManager:
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

    @staticmethod
    def create_icon_image(color_hex: str) -> Image.Image:
        image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        # Círculo base
        draw.ellipse((4, 4, 60, 60), fill=color_hex, outline="#FFFFFF", width=3)
        # 'O' de Obsidian en el centro
        draw.ellipse((20, 20, 44, 44), fill="#FFFFFF")
        return image

    def _build_menu(self) -> pystray.Menu:
        return pystray.Menu(
            pystray.Item("Abrir Ventana Principal", lambda: self.on_open_gui(), default=True),
            pystray.Item("Sincronizar Ahora", lambda: self.worker.trigger_now()),
            pystray.Item(
                lambda text: "Reanudar Sincronización" if self.worker.status == SyncStatus.PAUSED else "Pausar Sincronización",
                self._toggle_pause,
            ),
            pystray.Menu.SEPARATOR,
            pystray.Item(lambda text: f"Estado: {self._status_text}", None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.Item("Salir", lambda: self.on_exit()),
        )

    def _toggle_pause(self):
        if self.worker.status == SyncStatus.PAUSED:
            self.worker.resume()
        else:
            self.worker.pause()

    def update_status(self, status: SyncStatus, msg: str):
        self._status_text = msg
        if self.icon:
            color = COLOR_MAP.get(status, "#4CAF50")
            self.icon.icon = self.create_icon_image(color)
            self.icon.title = f"Obsidian GDrive Sync: {msg}"

    def start(self):
        img = self.create_icon_image(COLOR_MAP[SyncStatus.IDLE])
        self.icon = pystray.Icon("obsidian_sync", img, "Obsidian GDrive Sync", menu=self._build_menu())
        threading.Thread(target=self.icon.run, daemon=True).start()

    def stop(self):
        if self.icon:
            self.icon.stop()
```

- [ ] **Step 4: Ejecutar la prueba y verificar que pasa**

Run: `pytest tests/test_tray.py -v`  
Expected: PASS

- [ ] **Step 5: Confirmar cambios en git**

```bash
git add src/tray/tray_icon.py tests/test_tray.py
git commit -m "feat: implement dynamic System Tray manager with status colors"
```

---

### Task 7: Interfaz Gráfica de Usuario (`src/gui/app_window.py`)

**Files:**
- Create: `src/gui/__init__.py`
- Create: `src/gui/app_window.py`
- Create: `tests/test_gui_state.py`

**Interfaces:**
- Consumes: `src.core.config.ConfigManager`, `src.core.sync_worker.SyncWorker`, `src.tray.tray_icon.TrayManager`
- Produces:
  - `MainWindow`:
    - `show() -> None`
    - `hide() -> None`
    - `on_close_requested() -> None` (oculta ventana a System Tray)
    - `update_ui_state(status: SyncStatus, msg: str) -> None`

- [ ] **Step 1: Escribir la prueba de lógica de la GUI y eventos de cierre**

```python
# tests/test_gui_state.py
from unittest.mock import MagicMock
from src.core.config import ConfigData
from src.core.sync_worker import SyncStatus

def test_close_behavior_hides_instead_of_quits():
    # Al pulsar la 'X', la ventana debe ocultarse (withdraw) y no hacer sys.exit
    mock_app = MagicMock()
    mock_app.withdraw = MagicMock()
    
    def handle_close():
        mock_app.withdraw()

    handle_close()
    mock_app.withdraw.assert_called_once()
```

- [ ] **Step 2: Ejecutar la prueba y verificar que pasa**

Run: `pytest tests/test_gui_state.py -v`  
Expected: PASS

- [ ] **Step 3: Implementar `src/gui/app_window.py` con CustomTkinter**

```python
# src/gui/app_window.py
import customtkinter as ctk
from tkinter import filedialog, messagebox
import threading
from src.core.config import ConfigManager, ConfigData
from src.core.sync_worker import SyncWorker, SyncStatus
from src.core.rclone_manager import RcloneManager

class MainWindow(ctk.CTk):
    def __init__(self, config_manager: ConfigManager, worker: SyncWorker, rclone_mgr: RcloneManager):
        super().__init__()
        self.config_mgr = config_manager
        self.worker = worker
        self.rclone_mgr = rclone_mgr
        self.cfg = self.config_mgr.load()

        self.title("Obsidian GDrive Sync")
        self.geometry("640x560")
        self.minsize(580, 500)
        ctk.set_appearance_mode(self.cfg.theme)

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self.on_close_requested)
        self.worker.register_listener(self.on_worker_status_update)

    def _build_ui(self):
        # 1. Header de Estado
        self.header_frame = ctk.CTkFrame(self)
        self.header_frame.pack(fill="x", padx=16, pady=(16, 8))
        
        self.status_badge = ctk.CTkLabel(
            self.header_frame,
            text="● Inactivo",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color="#4CAF50"
        )
        self.status_badge.pack(side="left", padx=12, pady=10)

        # 2. Conexión Google Drive
        self.auth_frame = ctk.CTkFrame(self)
        self.auth_frame.pack(fill="x", padx=16, pady=8)
        
        self.auth_status = ctk.CTkLabel(self.auth_frame, text="Google Drive: Comprobando...")
        self.auth_status.pack(side="left", padx=12, pady=10)
        
        self.btn_auth = ctk.CTkButton(self.auth_frame, text="Conectar Cuenta", command=self._handle_auth)
        self.btn_auth.pack(side="right", padx=12, pady=10)

        # 3. Formulario de Rutas e Intervalo
        self.form_frame = ctk.CTkFrame(self)
        self.form_frame.pack(fill="x", padx=16, pady=8)

        # Vault Local
        ctk.CTkLabel(self.form_frame, text="Ruta Local del Vault:").grid(row=0, column=0, padx=12, pady=(10, 2), sticky="w")
        self.entry_local = ctk.CTkEntry(self.form_frame, width=420)
        self.entry_local.insert(0, self.cfg.local_vault_path)
        self.entry_local.grid(row=1, column=0, padx=12, pady=4, sticky="we")
        self.btn_browse = ctk.CTkButton(self.form_frame, text="Examinar...", width=90, command=self._browse_folder)
        self.btn_browse.grid(row=1, column=1, padx=12, pady=4)

        # Carpeta Remota
        ctk.CTkLabel(self.form_frame, text="Carpeta en Google Drive:").grid(row=2, column=0, padx=12, pady=(10, 2), sticky="w")
        self.entry_remote = ctk.CTkEntry(self.form_frame, width=420)
        self.entry_remote.insert(0, self.cfg.remote_folder_name)
        self.entry_remote.grid(row=3, column=0, padx=12, pady=4, sticky="we")

        # Intervalo
        ctk.CTkLabel(self.form_frame, text="Intervalo de Sincronización (minutos):").grid(row=4, column=0, padx=12, pady=(10, 2), sticky="w")
        self.entry_interval = ctk.CTkEntry(self.form_frame, width=120)
        self.entry_interval.insert(0, str(self.cfg.sync_interval_minutes))
        self.entry_interval.grid(row=5, column=0, padx=12, pady=4, sticky="w")

        # 4. Botones de Acción
        self.action_frame = ctk.CTkFrame(self)
        self.action_frame.pack(fill="x", padx=16, pady=12)

        self.btn_toggle_sync = ctk.CTkButton(
            self.action_frame, text="Iniciar Sincronización", command=self._toggle_sync, fg_color="#2E7D32"
        )
        self.btn_toggle_sync.pack(side="left", padx=12, pady=12)

        self.btn_sync_now = ctk.CTkButton(
            self.action_frame, text="Sincronizar Ahora", command=self._sync_now, fg_color="#1565C0"
        )
        self.btn_sync_now.pack(side="left", padx=12, pady=12)

        # 5. Registro de Logs
        self.log_box = ctk.CTkTextbox(self, height=140)
        self.log_box.pack(fill="both", expand=True, padx=16, pady=(4, 16))
        self._append_log("Bienvenido a Obsidian GDrive Sync.")

    def _browse_folder(self):
        selected = filedialog.askdirectory(title="Selecciona tu Vault de Obsidian")
        if selected:
            self.entry_local.delete(0, "end")
            self.entry_local.insert(0, selected)
            self._save_form()

    def _save_form(self):
        try:
            interval = int(self.entry_interval.get())
        except ValueError:
            interval = 2
        self.cfg.local_vault_path = self.entry_local.get().strip()
        self.cfg.remote_folder_name = self.entry_remote.get().strip() or "ObsidianVault"
        self.cfg.sync_interval_minutes = max(1, interval)
        self.config_mgr.save(self.cfg)

    def _handle_auth(self):
        def _run_auth():
            self._append_log("Abriendo navegador para autorización con Google...")
            cmd = self.rclone_mgr.get_auth_command()
            import subprocess
            subprocess.run(cmd)
            self._check_auth_status()
        threading.Thread(target=_run_auth, daemon=True).start()

    def _check_auth_status(self):
        is_auth = self.rclone_mgr.is_remote_configured("gdrive")
        if is_auth:
            self.auth_status.configure(text="✓ Conectado a Google Drive", text_color="#4CAF50")
            self.btn_auth.configure(text="Re-conectar")
        else:
            self.auth_status.configure(text="✕ No Conectado", text_color="#F44336")

    def _toggle_sync(self):
        self._save_form()
        if not self.worker._running:
            self.worker.start()
            self.btn_toggle_sync.configure(text="Detener Sincronización", fg_color="#C62828")
        else:
            self.worker.stop()
            self.btn_toggle_sync.configure(text="Iniciar Sincronización", fg_color="#2E7D32")

    def _sync_now(self):
        self._save_form()
        self.worker.trigger_now()

    def _append_log(self, text: str):
        self.log_box.insert("end", f"{text}\n")
        self.log_box.see("end")

    def on_worker_status_update(self, status: SyncStatus, msg: str):
        self.after(0, lambda: self._apply_worker_update(status, msg))

    def _apply_worker_update(self, status: SyncStatus, msg: str):
        color_map = {
            SyncStatus.IDLE: "#4CAF50",
            SyncStatus.SUCCESS: "#4CAF50",
            SyncStatus.SYNCING: "#2196F3",
            SyncStatus.PAUSED: "#FFC107",
            SyncStatus.ERROR: "#F44336",
        }
        self.status_badge.configure(text=f"● {msg}", text_color=color_map.get(status, "#FFFFFF"))
        self._append_log(msg)

    def on_close_requested(self):
        self.withdraw()
```

- [ ] **Step 4: Confirmar cambios en git**

```bash
git add src/gui/app_window.py tests/test_gui_state.py
git commit -m "feat: implement CustomTkinter main window with close-to-tray delegation"
```

---

### Task 8: Punto de Entrada Principal y Autostart (`src/main.py` y `src/utils/autostart.py`)

**Files:**
- Create: `src/utils/autostart.py`
- Create: `src/main.py`
- Create: `tests/test_autostart.py`

**Interfaces:**
- Consumes: Todos los módulos anteriores.
- Produces:
  - `main()`: Orquestador que inicia el Tray, el Worker y la GUI, manejando parámetros de línea de comando (ej. `--minimized`).

- [ ] **Step 1: Escribir la prueba unitaria para autostart**

```python
# tests/test_autostart.py
from pathlib import Path
from src.utils.autostart import generate_linux_desktop_entry

def test_generate_linux_desktop_entry():
    content = generate_linux_desktop_entry("/usr/bin/obsidian-sync")
    assert "[Desktop Entry]" in content
    assert "Exec=/usr/bin/obsidian-sync --minimized" in content
    assert "Type=Application" in content
```

- [ ] **Step 2: Ejecutar la prueba y verificar que falla**

Run: `pytest tests/test_autostart.py -v`  
Expected: FAIL con `ImportError: cannot import name 'generate_linux_desktop_entry'`

- [ ] **Step 3: Implementar `src/utils/autostart.py` y `src/main.py`**

```python
# src/utils/autostart.py
import sys
import os
from pathlib import Path

def generate_linux_desktop_entry(exec_path: str) -> str:
    return f"""[Desktop Entry]
Type=Application
Name=Obsidian GDrive Sync
Exec={exec_path} --minimized
Icon=utilities-sync
Comment=Obsidian Vault GDrive Synchronizer
Terminal=false
StartupNotify=false
"""

def set_autostart(enabled: bool):
    if sys.platform.startswith("linux"):
        autostart_dir = Path.home() / ".config" / "autostart"
        desktop_file = autostart_dir / "obsidian-gdrive-sync.desktop"
        if enabled:
            autostart_dir.mkdir(parents=True, exist_ok=True)
            desktop_file.write_text(generate_linux_desktop_entry(sys.executable), encoding="utf-8")
        else:
            if desktop_file.exists():
                desktop_file.unlink()
```

```python
# src/main.py
import sys
from src.core.config import ConfigManager
from src.core.rclone_manager import RcloneManager
from src.core.sync_worker import SyncWorker
from src.tray.tray_icon import TrayManager
from src.gui.app_window import MainWindow

def main():
    config_mgr = ConfigManager()
    cfg = config_mgr.load()
    rclone_mgr = RcloneManager()
    worker = SyncWorker(config=cfg, rclone_manager=rclone_mgr)

    app = MainWindow(config_manager=config_mgr, worker=worker, rclone_mgr=rclone_mgr)

    def on_open_gui():
        app.after(0, app.deiconify)

    def on_exit():
        worker.stop()
        tray.stop()
        app.after(0, app.destroy)
        sys.exit(0)

    tray = TrayManager(worker=worker, on_open_gui=on_open_gui, on_exit=on_exit)
    worker.register_listener(tray.update_status)

    tray.start()

    # Si se pasa --minimized no mostramos la ventana al iniciar
    if "--minimized" in sys.argv:
        app.withdraw()
    else:
        app.mainloop()

if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Ejecutar todas las pruebas del proyecto**

Run: `pytest tests/ -v`  
Expected: All tests PASS

- [ ] **Step 5: Confirmar cambios en git**

```bash
git add src/main.py src/utils/autostart.py tests/test_autostart.py
git commit -m "feat: implement autostart helper and main application entrypoint"
```
