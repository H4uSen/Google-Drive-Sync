# Obsidian GDrive Sync 🔄

Aplicación de escritorio moderna y multiplataforma (Windows y Linux) para sincronizar de forma continua, en tiempo real y bidireccional tus vaults de Obsidian (notas, imágenes, libros y PDFs) con Google Drive personal.

---

## 🌟 Características Principales

- **Sincronización Bidireccional Segura (`2-way bisync`)**: Los cambios locales suben a Google Drive y los cambios remotos bajan a tu computadora automáticamente sin sobrescrituras accidentales.
- **Detección de Cambios en Tiempo Real (`File Watcher`)**: Detección instantánea al guardar notas con debounce elástico configurable para evitar sincronizaciones innecesarias mientras escribes.
- **Soporte Multi-Vault y Perfiles**: Gestiona múltiples vaults independientes de Obsidian con carpetas remotas, intervalos y configuraciones individuales, alternando fácilmente desde un menú desplegable.
- **Monitor de Almacenamiento en Google Drive**: Visualización en tiempo real del espacio utilizado, disponible y total con barra de progreso codificada por color.
- **Integración Nativa con el Sistema (Autostart)**: Opción para arrancar automáticamente al iniciar sesión en Linux (especificación XDG) y Windows (Registro de Usuario `HKCU`), iniciando minimizado en segundo plano.
- **Bandeja del Sistema (System Tray) y Notificaciones**: Funciona discretamente en segundo plano junto al reloj del sistema, con notificaciones de escritorio y cooldown anti-spam de 15 minutos ante fallos de red.
- **Compatible 100% con Obsidian Git**: Excluye estrictamente `.git/**`, `.obsidian/workspace*.json`, cachés y temporales para evitar bucles de sincronización y permitir el uso simultáneo de Git y Google Drive.
- **Soporte de Archivos Pesados**: Sincroniza libros y PDFs grandes (>100 MB) en trozos reanudables con reintentos automáticos.
- **Empaquetado Standalone**: Preparado para generar binarios ejecutables portables e independientes con PyInstaller sin requerir Python en el equipo de destino.

---

## 🚀 Requisitos e Instalación

### Requisitos Previos
- Python 3.10 o superior (para ejecutar desde código fuente)
- Rclone ([https://rclone.org/downloads/](https://rclone.org/downloads/)) instalado en el sistema o en el PATH.

### Instalación Rápida desde Código Fuente

1. Clona o descarga este repositorio:
```bash
git clone <url-del-repo>
cd "Google Drive Sync"
```

2. Crea y activa un entorno virtual:
```bash
# En Linux:
python3 -m venv .venv
source .venv/bin/activate

# En Windows:
python -m venv .venv
.venv\Scripts\activate
```

3. Instala las dependencias:
```bash
pip install -r requirements.txt
```

---

## 💻 Uso de la Aplicación

Inicia la aplicación en modo normal:
```bash
# En Linux:
.venv/bin/python -m src.main

# En Windows:
.venv\Scripts\python -m src.main
```

O inicia minimizado en segundo plano (usado automáticamente por el autostart):
```bash
python -m src.main --minimized
```

### Configuración Rápida:
1. **Conectar Google Drive**: Haz clic en *"Conectar Cuenta"*. Se abrirá tu navegador para autorizar la conexión con Google Drive en un solo clic.
2. **Seleccionar Perfil y Vault**: Elige o crea un nuevo perfil de vault con el botón `+ Añadir`. Selecciona la carpeta local de tus notas con *"Examinar..."*.
3. **Preferencias**: Activa la *Sincronización en tiempo real* o el *Arranque automático con el sistema* según tus preferencias.
4. **Iniciar Sincronización**: Haz clic en *"Iniciar Sincronización"*.

### Menú de la Bandeja del Sistema (System Tray):
Haz clic derecho en el icono junto al reloj para:
- **Abrir Ventana Principal**: Vuelve a mostrar la interfaz gráfica.
- **Sincronizar Ahora**: Fuerza una sincronización inmediata.
- **Pausar / Reanudar**: Detiene o reactiva temporalmente las sincronizaciones programadas y del watcher.
- **Salir**: Cierra el daemon y apaga la aplicación limpiamente.

---

## 📦 Compilación y Empaquetado Standalone

Para compilar un ejecutable portable independiente (sin requerir Python en la máquina destino):

```bash
python packaging/build.py
```

El binario ejecutable (`obsidian-gdrive-sync` en Linux o `obsidian-gdrive-sync.exe` en Windows) se generará en la carpeta `dist/`.

---

## 🧪 Ejecutar Pruebas Automatizadas

Para validar todo el funcionamiento con la suite completa de 91 pruebas unitarias e integradas:

```bash
.venv/bin/pytest tests/ -v
```
