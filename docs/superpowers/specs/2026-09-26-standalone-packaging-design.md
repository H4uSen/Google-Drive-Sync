# Especificación Técnica: Empaquetado y Distribución Standalone

**Fecha:** 2026-09-26  
**Estado:** Propuesta Aprobada  
**Plataformas:** Windows (`.exe`) y Linux (`.AppImage` / binario standalone)  

---

## 1. Resumen Ejecutivo

Esta especificación detalla el proceso para congelar y empaquetar **Obsidian GDrive Sync** en ejecutables portables e independientes que no requieren que el usuario final tenga Python, git ni dependencias instaladas:
1. **Herramienta Base:** `PyInstaller` con archivo de especificación declarativo `packaging/obsidian-gdrive-sync.spec`.
2. **Inclusión de Recursos y Dependencias:**
   - Recursos gráficos de `customtkinter` (temas y assets JSON).
   - Módulos ocultos necesarios (`pystray`, `PIL`, `watchdog.observers.inotify`, `winreg` en Windows).
   - Inclusión automática del binario portable de Rclone o script de auto-descarga.
3. **Script de Construcción Unificado:** `packaging/build.py` automatiza la compilación con un solo comando para la plataforma actual.
4. **Verificación Automatizada:** Prueba de humo en pytest (`tests/test_packaging.py`) que valida la sintaxis de la spec de PyInstaller y la integridad de los assets.
