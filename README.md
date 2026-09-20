# Obsidian GDrive Sync 🔄

Aplicación de escritorio multiplataforma (Windows y Linux) para sincronizar de forma continua y bidireccional tu vault de Obsidian (notas, imágenes, libros y PDFs) con Google Drive personal.

---

## 🌟 Características Principales

- **Sincronización Bidireccional Segura (`2-way bisync`)**: Los cambios locales suben a Google Drive y los cambios remotos bajan a tu computadora.
- **Segundo Plano (System Tray)**: Al cerrar la ventana (`X`), la aplicación continúa funcionando silenciosamente en la bandeja del sistema junto al reloj.
- **Compatible 100% con Obsidian Git**: Excluye estrictamente la carpeta `.git/**` para que puedas seguir usando GitHub y Google Drive al mismo tiempo sin interferencias ni bloqueos.
- **Protección de Obsidian**: Excluye automáticamente `.obsidian/workspace.json`, cachés y temporales para evitar bucles de sincronización constantes.
- **Resolución de Conflictos sin Pérdida de Datos**: Si un archivo se modifica simultáneamente en ambos extremos, crea una copia segura con sufijo de conflicto (`.conflict-...`).
- **Soporte de Archivos Pesados**: Sincroniza libros y PDFs grandes (>100 MB) en trozos reanudables con reintentos automáticos.
- **Intervalo Configurable**: Por defecto sincroniza cada **2 minutos** (editable libremente en la interfaz).

---

## 🚀 Requisitos e Instalación

### Requisitos Previos
- Python 3.10 o superior
- Rclone ([https://rclone.org/downloads/](https://rclone.org/downloads/)) instalado en el sistema o en el PATH.

### Instalación Rápida

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

Inicia la aplicación:
```bash
# En Linux:
.venv/bin/python -m src.main

# En Windows:
.venv\Scripts\python -m src.main
```

### Configuración en 3 Pasos:
1. **Conectar Google Drive**: Haz clic en *"Conectar Cuenta"*. Se abrirá tu navegador para iniciar sesión en Google y autorizar el acceso a Google Drive en un solo clic.
2. **Seleccionar tu Vault**: Pulsa *"Examinar..."* y selecciona la carpeta local donde guardas tus notas de Obsidian.
3. **Iniciar Sincronización**: Pulsa *"Iniciar Sincronización"*.

¡Listo! Ya puedes cerrar la ventana; el programa continuará sincronizando tus notas cada 2 minutos en la bandeja del sistema.

### Menú de la Bandeja del Sistema (System Tray):
Haz clic derecho en el icono junto al reloj para:
- **Abrir Ventana Principal**: Vuelve a mostrar la interfaz gráfica.
- **Sincronizar Ahora**: Fuerza una sincronización inmediata sin esperar los 2 minutos.
- **Pausar / Reanudar**: Detiene o reactiva temporalmente las sincronizaciones.
- **Salir**: Detiene el daemon y cierra la aplicación por completo.

---

## 🧪 Ejecutar Pruebas Automatizadas

Para validar todo el funcionamiento con la suite de pruebas unitarias:
```bash
.venv/bin/pytest tests/ -v
```
