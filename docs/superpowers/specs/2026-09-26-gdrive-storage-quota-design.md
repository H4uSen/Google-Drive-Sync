# Especificación Técnica: Panel de Almacenamiento y Cuota en Google Drive

**Fecha:** 2026-09-26  
**Estado:** Propuesta Aprobada  
**Plataformas:** Windows (10/11) y Linux  

---

## 1. Resumen Ejecutivo

Esta especificación detalla el diseño para integrar métricas de almacenamiento y cuota de Google Drive dentro de la interfaz de **Obsidian GDrive Sync**:
1. **Consulta Asíncrona de Cuota:** Utilización de `rclone about gdrive: --json` para obtener el espacio total, usado, libre y en papelera de la cuenta de Google Drive configurada.
2. **Visualización Gráfica:** Barra de progreso (`CTkProgressBar`) e información en texto legible (ej. *"12.4 GB / 15.0 GB usados (82%)"*) en la sección de autenticación de Google Drive.
3. **Actualización Automática y Bajo Demanda:** Consulta automática en segundo plano tras autenticar la cuenta, tras una sincronización exitosa, y botón manual de actualización discreto.
4. **Cero Bloqueo de UI:** Todas las llamadas de inspección a Rclone se ejecutan en hilos daemon secundarios, actualizando la interfaz mediante `after(0, ...)`.

---

## 2. Objetivos y No-Objetivos

### Objetivos
- Mostrar el espacio total, usado y libre de la cuenta personal de Google Drive.
- Barra de progreso coloreada según el porcentaje de ocupación (verde < 75%, ámbar 75-90%, rojo > 90%).
- Manejar adecuadamente cuentas sin cuota fija (ej. Google Workspace ilimitado) o estados sin conexión.
- Ejecución 100% asíncrona sin congelar la ventana principal.

### No-Objetivos
- No se implementa un gestor de archivos remoto completo para borrar archivos de Google Drive (solo lectura de cuota).

---

## 3. Arquitectura y Componentes

### 3.1 Extensión de `RcloneManager` (`src/core/rclone_manager.py`)
- Método `get_storage_quota(remote_name: str = "gdrive") -> dict | None`:
  - Ejecuta: `[bin_cmd, "about", f"{remote_name}:", "--json"]` con timeout de 15 segundos.
  - Parsea la salida JSON:
    ```json
    {
      "total": 16106127360,
      "used": 12884901888,
      "trashed": 104857600,
      "free": 3221225472
    }
    ```
  - Devuelve un diccionario formateado o `None` si falla la red o no está autenticado.

### 3.2 Interfaz Gráfica (`src/gui/app_window.py`)
- En `self.auth_frame`:
  - Barra de cuota `self.quota_bar = ctk.CTkProgressBar(...)`.
  - Etiqueta `self.quota_label = ctk.CTkLabel(...)` mostrando: *"Cuota Drive: 12.0 GB / 15.0 GB (80%)"*.
  - Método asíncrono `_refresh_storage_quota()` disparado tras autorizar o al iniciar si la cuenta está conectada.
