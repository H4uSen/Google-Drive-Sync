# Especificación Técnica: Soporte Multi-Vault

**Fecha:** 2026-09-26  
**Estado:** Propuesta Aprobada  
**Plataformas:** Windows (10/11) y Linux  

---

## 1. Resumen Ejecutivo

Esta especificación define la evolución de **Obsidian GDrive Sync** para gestionar y sincronizar múltiples vaults independientes de Obsidian:
1. **Perfiles de Vaults (`VaultProfile`):** Cada vault tiene su propio nombre identificador, ruta local, carpeta remota en Google Drive, intervalo, y configuración de watcher en tiempo real.
2. **Selector Dinámico en la Interfaz Gráfica:** Menú desplegable (`CTkOptionMenu`) para alternar fácilmente entre vaults configurados, junto con botones para "Añadir Vault" y "Eliminar Vault".
3. **Migración Automática y Transparente:** Si existe un archivo `config.json` previo de vault único, se migra de inmediato a la lista de perfiles bajo el nombre *"Principal"*, sin pérdida de datos ni configuración previa.
4. **Orquestación de Sincronización:** Posibilidad de sincronizar el vault activo seleccionado o coordinar todos los vaults configurados de manera secuencial y segura.

---

## 2. Modelo de Datos (`src/core/config.py`)

```python
@dataclass
class VaultProfile:
    id: str
    name: str = "Mi Vault"
    local_path: str = ""
    remote_folder: str = "ObsidianVault"
    sync_interval_minutes: int = 2
    realtime_sync_enabled: bool = True
    debounce_delay_seconds: int = 5
    first_sync_done: bool = False
    last_sync_timestamp: str = ""
    last_sync_status: str = "idle"

@dataclass
class ConfigData:
    vaults: list[VaultProfile] = field(default_factory=list)
    active_vault_id: str = ""
    autostart_enabled: bool = False
    # Compatibilidad con accesores de vault activo
```

---

## 3. Interfaz Gráfica (`src/gui/app_window.py`)
- Selector superior: `CTkOptionMenu` con la lista de vaults.
- Diálogo modal simple para crear un nuevo perfil de vault pidiendo Nombre, Ruta local y Carpeta remota.
- Al alternar el vault seleccionado, el formulario se actualiza al instante con los datos del perfil activo.
