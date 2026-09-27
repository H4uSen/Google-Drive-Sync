# Empaquetado y Distribución Standalone Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Proveer empaquetado autónomo con PyInstaller para generar ejecutables portables sin dependencias de Python.

**Architecture:** Archivo declarativo `packaging/obsidian-gdrive-sync.spec` con recolección de datos de CustomTkinter, imports ocultos de pystray/watchdog y script `packaging/build.py`.

**Tech Stack:** Python 3.10+, PyInstaller, Pytest.

**Spec:** `docs/superpowers/specs/2026-09-26-standalone-packaging-design.md`

## Global Constraints
- Scripts de empaquetado autónomos y reproducibles.
- Validación de que los assets de CustomTkinter y dependencias ocultas se incluyan correctamente.

---

### Task 1: Archivo Spec de PyInstaller y Script de Compilación (`packaging/`)
- Create: `packaging/obsidian-gdrive-sync.spec`
- Create: `packaging/build.py`
- Test: `tests/test_packaging.py`
- [ ] Step 1: Escribir prueba de validación de sintaxis de la spec y presencia de assets.
- [ ] Step 2: Implementar spec y script `packaging/build.py`.
- [ ] Step 3: Verificar que pasa la prueba.
- [ ] Step 4: Commit.
