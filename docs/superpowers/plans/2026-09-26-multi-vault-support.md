# Soporte Multi-Vault Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Permitir gestionar y sincronizar múltiples vaults independientes de Obsidian con perfiles individuales y selector en la GUI.

**Architecture:** Modelos `VaultProfile` y `ConfigData` con soporte de lista de vaults y migración transparente de configs mono-vault; selector `CTkOptionMenu` en `app_window.py` para alternar perfiles en caliente con botones de creación/eliminación.

**Tech Stack:** Python 3.10+, CustomTkinter, Pytest.

**Spec:** `docs/superpowers/specs/2026-09-26-multi-vault-support-design.md`

## Global Constraints
- Migración 100% transparente: no perder ningún vault ni dato de config previa.
- Manejo seguro de borrado de perfiles (al menos un vault debe quedar activo).

---

### Task 1: Modelo `VaultProfile` y Migración en `ConfigData` (`src/core/config.py`)
- Modify: `src/core/config.py`
- Test: `tests/test_config.py`
- [ ] Step 1: Escribir prueba de migración mono-vault a multi-vault.
- [ ] Step 2: Verificar fallo.
- [ ] Step 3: Implementar `VaultProfile`, campos en `ConfigData` y métodos de migración/acceso.
- [ ] Step 4: Verificar que pasa la prueba.
- [ ] Step 5: Commit.

### Task 2: Selector y Gestión de Vaults en `MainWindow` (`src/gui/app_window.py`)
- Modify: `src/gui/app_window.py`
- Test: `tests/test_gui_state.py`
- [ ] Step 1: Escribir prueba de cambio de perfil activo y renderizado de controles.
- [ ] Step 2: Verificar fallo.
- [ ] Step 3: Implementar selector `CTkOptionMenu`, diálogos de añadir/eliminar vault.
- [ ] Step 4: Verificar que pasa la prueba.
- [ ] Step 5: Commit.
