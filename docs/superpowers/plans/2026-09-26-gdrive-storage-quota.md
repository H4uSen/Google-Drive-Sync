# Panel de Almacenamiento y Cuota en Google Drive Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mostrar métricas visuales de almacenamiento y cuota de Google Drive (`rclone about gdrive: --json`) con barra de progreso y actualización asíncrona.

**Architecture:** Método `get_storage_quota()` en `RcloneManager` ejecutando `rclone about`; integración en `MainWindow` con barra `CTkProgressBar`, etiqueta formateada y refresco en segundo plano sin congelar la interfaz.

**Tech Stack:** Python 3.10+, Rclone CLI, CustomTkinter, Pytest.

**Spec:** `docs/superpowers/specs/2026-09-26-gdrive-storage-quota-design.md`

## Global Constraints
- Ejecución 100% asíncrona en hilo daemon con `self.after(0, ...)`.
- Formato amigable en GB o MB según el tamaño.
- Manejo seguro de errores de red o cuota no reportada (devolviendo None o dict vacío sin crashear).

---

### Task 1: Método `get_storage_quota` en `RcloneManager` (`src/core/rclone_manager.py`)
- Modify: `src/core/rclone_manager.py`
- Test: `tests/test_rclone_manager.py`
- [ ] Step 1: Escribir prueba unitaria que simula `rclone about gdrive: --json`.
- [ ] Step 2: Verificar fallo de prueba.
- [ ] Step 3: Implementar `get_storage_quota()`.
- [ ] Step 4: Verificar que pasa la prueba.
- [ ] Step 5: Commit.

### Task 2: Componentes Gráficos de Cuota en `MainWindow` (`src/gui/app_window.py`)
- Modify: `src/gui/app_window.py`
- Test: `tests/test_gui_state.py`
- [ ] Step 1: Escribir prueba de widgets de cuota.
- [ ] Step 2: Verificar fallo.
- [ ] Step 3: Implementar `quota_bar`, `quota_label` y método asíncrono `_refresh_storage_quota()`.
- [ ] Step 4: Verificar que pasa la prueba.
- [ ] Step 5: Commit.
