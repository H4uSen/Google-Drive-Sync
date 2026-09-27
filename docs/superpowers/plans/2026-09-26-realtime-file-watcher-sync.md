# Sincronización en Tiempo Real (File Watcher con Debounce) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrar detección reactiva de cambios en el sistema de archivos del vault de Obsidian mediante `watchdog` con debounce elástico configurable y encolamiento concurrente para sincronización casi instantánea.

**Architecture:** Módulo reactivo `src/core/vault_watcher.py` con filtrado estricto de rutas excluidas (`.git`, `.obsidian/workspace`, `.obsidian/cache`, `*.tmp`) y debounce con `threading.Timer`; coordinación en `src/core/sync_worker.py` gestionando el ciclo de vida del watcher y el encolamiento de sincronizaciones pendientes (`_pending_sync`) para evitar colisiones; y controles de configuración en `src/gui/app_window.py`.

**Tech Stack:** Python 3.10+, watchdog>=4.0.0, CustomTkinter, Pytest.

**Spec:** `docs/superpowers/specs/2026-09-26-realtime-file-watcher-sync-design.md`

## Global Constraints

- Plataformas soportadas: Linux y Windows.
- Dependencia externa requerida: `watchdog>=4.0.0` registrada en `requirements.txt`.
- Exclusiones estrictas del watcher: `.git`, `.git/**`, `.gitignore`, `.git-credentials`, `.obsidian/workspace.json`, `.obsidian/workspace-mobile.json`, `.obsidian/cache/**`, `.obsidian/plugins/obsidian-git/data.json`, `*.tmp`, `*~`, `*.swp`.
- Debounce elástico: Cada evento reinicia el temporizador de inactividad (`debounce_delay_seconds`), disparando la sincronización solo cuando cesa la escritura.
- Encolamiento de sincronizaciones: Si el worker está ocupado ejecutando rclone, los eventos del watcher marcan `_pending_sync = True` para disparar una nueva sincronización inmediatamente después de que termine la actual.
- Apagado limpio: `worker.stop()` cancela cualquier temporizador pendiente y detiene el hilo del `Observer` sin fugas de recursos.

## Review Focus

1. **Ráfaga continua de guardados automáticos de Obsidian:** Al tipear rápido, Obsidian genera eventos cada segundo; el debounce debe posponerse continuamente sin disparar procesos intermedios hasta que haya una pausa real.
2. **Eventos ocurridos durante una sincronización activa:** Si se modifica un archivo mientras rclone está corriendo en segundo plano, no debe ignorarse el cambio; debe marcar `_pending_sync = True` y dispararse al terminar el proceso actual.
3. **Falsos positivos de archivos de estado interno de Obsidian:** La edición de notas actualiza `.obsidian/workspace.json` y cachés; estos eventos deben filtrarse de forma absoluta para no causar bucles infinitos de sincronización.
4. **Modificaciones de configuración en caliente:** Si el usuario desmarca la sincronización en tiempo real o cambia los segundos de debounce en la GUI con la sincronización activa, el watcher debe adaptarse inmediatamente sin requerir reiniciar la aplicación.
5. **Cierre de aplicación con temporizador pendiente:** Si el usuario cierra o detiene la sincronización mientras un temporizador de debounce de 5s está a la mitad, no debe dispararse un callback huérfano ni generar errores de hilo.

---

### Task 1: Dependencias y Modelo de Configuración (`requirements.txt` y `ConfigData`)

**Files:**
- Modify: `requirements.txt`
- Modify: `src/core/config.py:12-28`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: `ConfigData` existente.
- Produces:
  - `ConfigData.realtime_sync_enabled: bool = True`
  - `ConfigData.debounce_delay_seconds: int = 5`

- [ ] **Step 1: Write the failing test**

Añadir en `tests/test_config.py`:
```python
def test_config_realtime_sync_defaults_and_validation(tmp_path):
    config_file = tmp_path / "config.json"
    mgr = ConfigManager(config_file=config_file)
    cfg = mgr.load()
    assert cfg.realtime_sync_enabled is True
    assert cfg.debounce_delay_seconds == 5

    # Validación de límites en clean()
    cfg.debounce_delay_seconds = 0
    cfg.clean()
    assert cfg.debounce_delay_seconds == 5

    cfg.debounce_delay_seconds = 10
    mgr.save(cfg)
    loaded = mgr.load()
    assert loaded.debounce_delay_seconds == 10
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_config.py::test_config_realtime_sync_defaults_and_validation -v`  
Expected: FAIL con `AttributeError: 'ConfigData' object has no attribute 'realtime_sync_enabled'`

- [ ] **Step 3: Write minimal implementation**

1. En `requirements.txt`:
```text
customtkinter>=5.2.0
pystray>=0.19.5
pillow>=10.0.0
pytest>=8.0.0
watchdog>=4.0.0
```

2. En `src/core/config.py`:
Añadir atributos a `ConfigData`:
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
    realtime_sync_enabled: bool = True
    debounce_delay_seconds: int = 5

    def clean(self):
        if not isinstance(self.sync_interval_minutes, int) or self.sync_interval_minutes < 1:
            self.sync_interval_minutes = 2
        if not isinstance(self.debounce_delay_seconds, int) or self.debounce_delay_seconds < 1:
            self.debounce_delay_seconds = 5
        if not self.remote_folder_name.strip():
            self.remote_folder_name = "ObsidianVault"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_config.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add requirements.txt src/core/config.py tests/test_config.py
git commit -m "feat(config): add watchdog dependency and realtime sync config fields"
```

---

### Task 2: Módulo `src/core/vault_watcher.py` (VaultChangeHandler y VaultWatcher)

**Files:**
- Create: `src/core/vault_watcher.py`
- Test: `tests/test_vault_watcher.py`

**Interfaces:**
- Consumes: `watchdog.observers.Observer`, `watchdog.events.FileSystemEventHandler`.
- Produces:
  - `class VaultChangeHandler(FileSystemEventHandler)`
  - `class VaultWatcher`
  - Filtrado de exclusiones y debounce elástico con `threading.Timer`.

- [ ] **Step 1: Write the failing tests**

Crear `tests/test_vault_watcher.py`:
```python
import time
from pathlib import Path
from unittest.mock import MagicMock
from src.core.vault_watcher import VaultChangeHandler, VaultWatcher

def test_vault_change_handler_should_ignore_rules():
    handler = VaultChangeHandler(callback=MagicMock(), debounce_seconds=1.0)
    
    # Exclusiones estrictas
    assert handler.should_ignore(".git") is True
    assert handler.should_ignore(".git/config") is True
    assert handler.should_ignore("subfolder/.git/index") is True
    assert handler.should_ignore(".gitignore") is True
    assert handler.should_ignore(".obsidian/workspace.json") is True
    assert handler.should_ignore(".obsidian/workspace-mobile.json") is True
    assert handler.should_ignore(".obsidian/cache/indexed.bin") is True
    assert handler.should_ignore("note.tmp") is True
    assert handler.should_ignore(".obsidian/plugins/obsidian-git/data.json") is True

    # Archivos válidos que sí deben procesarse
    assert handler.should_ignore("MyNote.md") is False
    assert handler.should_ignore("folder/subnote.md") is False
    assert handler.should_ignore("assets/image.png") is False
    assert handler.should_ignore("books/doc.pdf") is False

def test_vault_change_handler_debounce_coalescing():
    callback = MagicMock()
    handler = VaultChangeHandler(callback=callback, debounce_seconds=0.1)

    # Simular ráfaga de 5 eventos seguidos
    for i in range(5):
        handler._on_valid_change()
        time.sleep(0.02)

    # Antes del tiempo de debounce no debe haber llamado
    assert callback.call_count == 0

    # Esperamos a que expire el debounce (0.1s + margen)
    time.sleep(0.15)
    assert callback.call_count == 1

def test_vault_watcher_cleanup_cancels_timer():
    callback = MagicMock()
    handler = VaultChangeHandler(callback=callback, debounce_seconds=0.1)
    handler._on_valid_change()
    assert handler._timer is not None

    handler.stop()
    assert handler._timer is None
    time.sleep(0.15)
    assert callback.call_count == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_vault_watcher.py -v`  
Expected: FAIL con `ModuleNotFoundError: No module named 'src.core.vault_watcher'`

- [ ] **Step 3: Write minimal implementation**

Crear `src/core/vault_watcher.py`:
```python
import os
import sys
import threading
import logging
from pathlib import Path
from typing import Callable
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileSystemEvent

logger = logging.getLogger(__name__)

IGNORED_SUBSTRINGS = [
    "/.git/",
    "/.git",
    "/.obsidian/cache/",
    "/.obsidian/cache",
]

IGNORED_EXACT_NAMES = {
    ".git",
    ".gitignore",
    ".git-credentials",
    "workspace.json",
    "workspace-mobile.json",
    "data.json",
}

class VaultChangeHandler(FileSystemEventHandler):
    def __init__(self, callback: Callable[[], None], debounce_seconds: float = 5.0):
        super().__init__()
        self.callback = callback
        self.debounce_seconds = max(0.5, float(debounce_seconds))
        self._timer: threading.Timer | None = None
        self._lock = threading.Lock()

    def should_ignore(self, path: str) -> bool:
        if not path:
            return True
        norm = path.replace("\\", "/")
        parts = [p for p in norm.split("/") if p]
        if not parts:
            return True

        if ".git" in parts:
            return True

        filename = parts[-1]
        if filename in IGNORED_EXACT_NAMES:
            return True

        if filename.endswith(".tmp") or filename.endswith("~") or filename.endswith(".swp"):
            return True

        if ".obsidian" in parts:
            obsidian_idx = parts.index(".obsidian")
            sub_parts = parts[obsidian_idx + 1:]
            if sub_parts and sub_parts[0] in ("cache", "workspace.json", "workspace-mobile.json"):
                return True
            if len(sub_parts) >= 3 and sub_parts[0] == "plugins" and sub_parts[1] == "obsidian-git" and sub_parts[2] == "data.json":
                return True

        return False

    def _on_valid_change(self):
        with self._lock:
            if self._timer:
                self._timer.cancel()
            self._timer = threading.Timer(self.debounce_seconds, self._fire_callback)
            self._timer.daemon = True
            self._timer.start()

    def _fire_callback(self):
        with self._lock:
            self._timer = None
        try:
            self.callback()
        except Exception as e:
            logger.error(f"Error in vault watcher callback: {e}")

    def on_any_event(self, event: FileSystemEvent):
        # Descartar eventos de directorios puros
        if event.is_directory:
            return

        src_path = getattr(event, "src_path", "")
        if self.should_ignore(src_path):
            return

        dest_path = getattr(event, "dest_path", None)
        if dest_path and self.should_ignore(dest_path):
            return

        self._on_valid_change()

    def stop(self):
        with self._lock:
            if self._timer:
                self._timer.cancel()
                self._timer = None

class VaultWatcher:
    def __init__(self, callback: Callable[[], None], debounce_seconds: float = 5.0):
        self.callback = callback
        self.debounce_seconds = debounce_seconds
        self.handler = VaultChangeHandler(callback=self.callback, debounce_seconds=self.debounce_seconds)
        self.observer: Observer | None = None
        self._running = False

    def start(self, vault_path: str):
        if self._running:
            return
        p = Path(vault_path).resolve()
        if not p.is_dir():
            logger.warning(f"No se puede iniciar VaultWatcher: ruta no válida ({vault_path})")
            return
        try:
            self.observer = Observer()
            self.observer.schedule(self.handler, str(p), recursive=True)
            self.observer.daemon = True
            self.observer.start()
            self._running = True
            logger.info(f"VaultWatcher iniciado en {p} (debounce: {self.debounce_seconds}s)")
        except Exception as e:
            logger.error(f"Error al iniciar VaultWatcher: {e}")

    def stop(self):
        if not self._running:
            return
        self._running = False
        self.handler.stop()
        if self.observer:
            try:
                self.observer.stop()
                self.observer.join(timeout=2)
            except Exception as e:
                logger.debug(f"Error deteniendo observer: {e}")
            self.observer = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_vault_watcher.py -v`  
Expected: PASS en todos los casos de prueba de filtrado y debounce.

- [ ] **Step 5: Commit**

```bash
git add src/core/vault_watcher.py tests/test_vault_watcher.py
git commit -m "feat(watcher): implement VaultChangeHandler and VaultWatcher with debouncing and exclusions"
```

---

### Task 3: Integración de Watcher y Encolamiento Concurrente en `SyncWorker`

**Files:**
- Modify: `src/core/sync_worker.py`
- Test: `tests/test_sync_worker_watcher.py`

**Interfaces:**
- Consumes: `VaultWatcher`, `ConfigData.realtime_sync_enabled`, `ConfigData.debounce_delay_seconds`.
- Produces:
  - Inicialización y ciclo de vida de `VaultWatcher` dentro de `SyncWorker`.
  - Manejo de `_pending_sync = True` cuando hay cambios durante una sincronización activa.

- [ ] **Step 1: Write the failing tests**

Crear `tests/test_sync_worker_watcher.py`:
```python
import time
from unittest.mock import MagicMock, patch
from src.core.config import ConfigData
from src.core.sync_worker import SyncWorker, SyncStatus

def test_sync_worker_watcher_lifecycle(tmp_path):
    vault = tmp_path / "my_vault"
    vault.mkdir()
    cfg = ConfigData(local_vault_path=str(vault), realtime_sync_enabled=True)
    worker = SyncWorker(config=cfg, rclone_manager=MagicMock())

    with patch("src.core.sync_worker.VaultWatcher") as mock_watcher_cls:
        mock_watcher = MagicMock()
        mock_watcher_cls.return_value = mock_watcher

        worker.start()
        assert worker.watcher is not None
        mock_watcher.start.assert_called_once_with(str(vault))

        worker.stop()
        mock_watcher.stop.assert_called_once()

def test_sync_worker_queues_pending_sync_when_busy(tmp_path):
    vault = tmp_path / "my_vault"
    vault.mkdir()
    cfg = ConfigData(local_vault_path=str(vault))
    worker = SyncWorker(config=cfg, rclone_manager=MagicMock())

    # Simular estado ocupado
    worker._is_syncing = True
    worker._on_watcher_change()
    assert worker._pending_sync is True

    # Cuando no está ocupado, debe disparar wakeup
    worker._is_syncing = False
    assert not worker._wakeup_event.is_set()
    worker._on_watcher_change()
    assert worker._wakeup_event.is_set()

def test_sync_worker_watcher_ignores_events_when_paused(tmp_path):
    vault = tmp_path / "my_vault"
    vault.mkdir()
    cfg = ConfigData(local_vault_path=str(vault))
    worker = SyncWorker(config=cfg, rclone_manager=MagicMock())

    worker.pause()
    worker._on_watcher_change()
    assert worker._pending_sync is False
    assert not worker._wakeup_event.is_set()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_sync_worker_watcher.py -v`  
Expected: FAIL con `AttributeError: 'SyncWorker' object has no attribute 'watcher'` o `_on_watcher_change`

- [ ] **Step 3: Write minimal implementation**

En `src/core/sync_worker.py`:
1. Importar `VaultWatcher`:
```python
from src.core.vault_watcher import VaultWatcher
```
2. En `__init__`:
```python
        self.watcher: VaultWatcher | None = None
        self._pending_sync = False
```
3. Añadir el manejador de cambios del watcher:
```python
    def _on_watcher_change(self):
        if self._paused or not self._running:
            return
        if self._is_syncing or self._sync_lock.locked():
            logger.info("Cambios detectados durante sincronización activa. Marcando sincronización pendiente.")
            self._pending_sync = True
            return
        self._wakeup_event.set()
```
4. En `_execute_sync()`, en el bloque `finally`:
```python
        finally:
            self._is_syncing = False
            self._sync_lock.release()
            if self._pending_sync:
                self._pending_sync = False
                logger.info("Ejecutando sincronización pendiente por cambios locales...")
                self._wakeup_event.set()
```
5. En `start()`:
```python
    def start(self):
        if self._running:
            return
        self._running = True
        if self.config.realtime_sync_enabled and self.config.local_vault_path:
            self.watcher = VaultWatcher(
                callback=self._on_watcher_change,
                debounce_seconds=getattr(self.config, "debounce_delay_seconds", 5),
            )
            self.watcher.start(self.config.local_vault_path)
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
```
6. En `stop()`:
```python
    def stop(self):
        self._running = False
        if self.watcher:
            self.watcher.stop()
            self.watcher = None
        self._wakeup_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_sync_worker_watcher.py tests/test_sync_worker.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/core/sync_worker.py tests/test_sync_worker_watcher.py
git commit -m "feat(worker): integrate VaultWatcher and pending sync queue into SyncWorker"
```

---

### Task 4: Controles de Configuración en la Interfaz Gráfica (`src/gui/app_window.py`)

**Files:**
- Modify: `src/gui/app_window.py`
- Test: `tests/test_gui_state.py`

**Interfaces:**
- Consumes: `ConfigData.realtime_sync_enabled`, `ConfigData.debounce_delay_seconds`.
- Produces:
  - Checkbox para activar/desactivar tiempo real.
  - Entrada de segundos de debounce.
  - Actualización en caliente de `worker.watcher`.

- [ ] **Step 1: Write the failing test**

Añadir en `tests/test_gui_state.py`:
```python
def test_gui_realtime_sync_form_persistence(tmp_path):
    vault = tmp_path / "valid_vault"
    vault.mkdir()
    cfg = ConfigData(local_vault_path=str(vault), realtime_sync_enabled=True, debounce_delay_seconds=8)
    mock_cfg_mgr = MagicMock()
    mock_cfg_mgr.load.return_value = cfg
    mock_worker = MagicMock()
    mock_rclone = MagicMock()

    with patch("customtkinter.CTk.__init__", return_value=None):
        win = MainWindow(config_manager=mock_cfg_mgr, worker=mock_worker, rclone_mgr=mock_rclone)
        assert hasattr(win, "chk_realtime")
        assert hasattr(win, "entry_debounce")
        assert win.cfg.debounce_delay_seconds == 8
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_gui_state.py::test_gui_realtime_sync_form_persistence -v`  
Expected: FAIL con `AttributeError: 'MainWindow' object has no attribute 'chk_realtime'`

- [ ] **Step 3: Write minimal implementation**

En `src/gui/app_window.py`:
1. En `_build_ui`, en `form_frame`:
```python
        # Checkbox Sincronización en tiempo real
        self.chk_realtime = ctk.CTkCheckBox(
            self.form_frame,
            text="Sincronización en tiempo real (detectar cambios al guardar)",
            font=ctk.CTkFont(size=13),
            command=self._save_form,
        )
        self.chk_realtime.grid(row=7, column=0, columnspan=2, padx=16, pady=(4, 4), sticky="w")
        if self.cfg.realtime_sync_enabled:
            self.chk_realtime.select()
        else:
            self.chk_realtime.deselect()

        # Fila Debounce Seconds
        self.debounce_row = ctk.CTkFrame(self.form_frame, fg_color="transparent")
        self.debounce_row.grid(row=8, column=0, columnspan=2, padx=16, pady=(2, 10), sticky="w")
        ctk.CTkLabel(self.debounce_row, text="Espera tras escribir (segundos):", font=ctk.CTkFont(size=12)).pack(side="left", padx=(0, 8))
        self.entry_debounce = ctk.CTkEntry(self.debounce_row, width=60)
        self.entry_debounce.insert(0, str(self.cfg.debounce_delay_seconds))
        self.entry_debounce.pack(side="left")
```
2. En `_save_form()`:
```python
        try:
            debounce = int(self.entry_debounce.get())
        except ValueError:
            debounce = 5
        self.cfg.debounce_delay_seconds = max(1, min(60, debounce))
        self.cfg.realtime_sync_enabled = bool(self.chk_realtime.get())
        self.config_mgr.save(self.cfg)
        self.worker.config = self.cfg

        # Actualizar watcher en caliente si el worker está activo
        if self.worker._running:
            if not self.cfg.realtime_sync_enabled and self.worker.watcher:
                self.worker.watcher.stop()
                self.worker.watcher = None
            elif self.cfg.realtime_sync_enabled and not self.worker.watcher and self.cfg.local_vault_path:
                from src.core.vault_watcher import VaultWatcher
                self.worker.watcher = VaultWatcher(
                    callback=self.worker._on_watcher_change,
                    debounce_seconds=self.cfg.debounce_delay_seconds,
                )
                self.worker.watcher.start(self.cfg.local_vault_path)
            elif self.worker.watcher:
                self.worker.watcher.handler.debounce_seconds = self.cfg.debounce_delay_seconds
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_gui_state.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/gui/app_window.py tests/test_gui_state.py
git commit -m "feat(gui): add realtime sync checkbox and debounce input with hot reload"
```

---

### Task 5: Verificación Integral y Suite Completa

**Files:**
- Test: Todas las suites de pruebas en `tests/`

- [ ] **Step 1: Run full test suite**

Run: `.venv/bin/pytest tests/ -v`  
Expected: 100% PASS en todas las pruebas (sin advertencias ni regresiones).

- [ ] **Step 2: Git status and cleanliness check**

Run: `git status -s`  
Expected: Árbol de trabajo limpio y todos los commits confirmados.
