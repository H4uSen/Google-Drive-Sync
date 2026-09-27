import sys
import threading
import subprocess
from pathlib import Path
from tkinter import filedialog
import customtkinter as ctk
from src.core.config import ConfigManager, ConfigData
from src.core.sync_worker import SyncWorker, SyncStatus, COLOR_MAP
from src.core.rclone_manager import RcloneManager

STATUS_COLORS = COLOR_MAP

class MainWindow(ctk.CTk):
    def __init__(self, config_manager: ConfigManager, worker: SyncWorker, rclone_mgr: RcloneManager):
        super().__init__()
        self.config_mgr = config_manager
        self.worker = worker
        self.rclone_mgr = rclone_mgr
        self.cfg = self.config_mgr.load()

        self.title("Obsidian GDrive Sync")
        self.geometry("680x600")
        self.minsize(600, 520)
        ctk.set_appearance_mode("dark")

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self.on_close_requested)
        self.worker.register_listener(self.on_worker_status_update)
        self._check_auth_status()

    def _build_ui(self):
        # 1. Header de Estado
        self.header_frame = ctk.CTkFrame(self, corner_radius=8)
        self.header_frame.pack(fill="x", padx=16, pady=(16, 8))
        
        self.status_badge = ctk.CTkLabel(
            self.header_frame,
            text="● Inactivo",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=STATUS_COLORS[SyncStatus.IDLE]
        )
        self.status_badge.pack(side="left", padx=16, pady=12)

        # 2. Conexión Google Drive
        self.auth_frame = ctk.CTkFrame(self, corner_radius=8)
        self.auth_frame.pack(fill="x", padx=16, pady=8)
        
        self.auth_status = ctk.CTkLabel(
            self.auth_frame,
            text="Google Drive: Comprobando conexión...",
            font=ctk.CTkFont(size=13)
        )
        self.auth_status.pack(side="left", padx=16, pady=12)
        
        self.btn_auth = ctk.CTkButton(
            self.auth_frame,
            text="Conectar Cuenta",
            command=self._handle_auth,
            width=140
        )
        self.btn_auth.pack(side="right", padx=16, pady=12)

        # 3. Formulario de Configuración
        self.form_frame = ctk.CTkFrame(self, corner_radius=8)
        self.form_frame.pack(fill="x", padx=16, pady=8)
        self.form_frame.grid_columnconfigure(0, weight=1)

        # Vault Local
        ctk.CTkLabel(
            self.form_frame,
            text="Ruta Local del Vault de Obsidian:",
            font=ctk.CTkFont(weight="bold")
        ).grid(row=0, column=0, padx=16, pady=(12, 2), sticky="w")
        
        self.local_row = ctk.CTkFrame(self.form_frame, fg_color="transparent")
        self.local_row.grid(row=1, column=0, columnspan=2, padx=16, pady=4, sticky="we")
        self.local_row.grid_columnconfigure(0, weight=1)

        self.entry_local = ctk.CTkEntry(self.local_row, placeholder_text="/ruta/a/tu/ObsidianVault")
        self.entry_local.insert(0, self.cfg.local_vault_path)
        self.entry_local.grid(row=0, column=0, padx=(0, 8), sticky="we")

        self.btn_browse = ctk.CTkButton(self.local_row, text="Examinar...", width=100, command=self._browse_folder)
        self.btn_browse.grid(row=0, column=1)

        # Carpeta Remota
        ctk.CTkLabel(
            self.form_frame,
            text="Carpeta de Destino en Google Drive:",
            font=ctk.CTkFont(weight="bold")
        ).grid(row=2, column=0, padx=16, pady=(12, 2), sticky="w")
        
        self.entry_remote = ctk.CTkEntry(self.form_frame, placeholder_text="ObsidianVault")
        self.entry_remote.insert(0, self.cfg.remote_folder_name)
        self.entry_remote.grid(row=3, column=0, columnspan=2, padx=16, pady=4, sticky="we")

        # Intervalo
        ctk.CTkLabel(
            self.form_frame,
            text="Intervalo de Sincronización Continua (minutos):",
            font=ctk.CTkFont(weight="bold")
        ).grid(row=4, column=0, padx=16, pady=(12, 2), sticky="w")
        
        self.entry_interval = ctk.CTkEntry(self.form_frame, width=120)
        self.entry_interval.insert(0, str(self.cfg.sync_interval_minutes))
        self.entry_interval.grid(row=5, column=0, padx=16, pady=(4, 14), sticky="w")

        # 4. Acciones Principales
        self.action_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.action_frame.pack(fill="x", padx=16, pady=10)

        self.btn_toggle_sync = ctk.CTkButton(
            self.action_frame,
            text="Iniciar Sincronización",
            command=self._toggle_sync,
            fg_color="#2E7D32",
            hover_color="#1B5E20",
            font=ctk.CTkFont(weight="bold")
        )
        self.btn_toggle_sync.pack(side="left", padx=(0, 10))

        self.btn_sync_now = ctk.CTkButton(
            self.action_frame,
            text="Sincronizar Ahora",
            command=self._sync_now,
            fg_color="#1565C0",
            hover_color="#0D47A1",
            font=ctk.CTkFont(weight="bold")
        )
        self.btn_sync_now.pack(side="left", padx=10)

        # 5. Panel de Logs
        ctk.CTkLabel(self, text="Registro de Actividad:", font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=20, pady=(4, 2))
        self.log_box = ctk.CTkTextbox(self, height=140, corner_radius=8)
        self.log_box.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        self._append_log("Bienvenido a Obsidian GDrive Sync.")
        self._append_log("Configuración cargada correctamente.")

    def _browse_folder(self):
        selected = filedialog.askdirectory(title="Selecciona la Carpeta de tu Vault de Obsidian")
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

        raw_remote = self.entry_remote.get().strip().strip("/\\").replace("\\", "/")
        parts = [p for p in raw_remote.split("/") if p]
        if not raw_remote or raw_remote == "." or ".." in parts:
            raw_remote = "ObsidianVault"
        self.cfg.remote_folder_name = raw_remote

        self.cfg.sync_interval_minutes = max(1, interval)
        self.config_mgr.save(self.cfg)
        self.worker.config = self.cfg

    def _handle_auth(self):
        def _run_auth():
            self._append_log("Iniciando asistente de conexión con Google Drive en el navegador...")
            cmd = self.rclone_mgr.get_auth_command()
            try:
                subprocess.run(cmd, stdin=subprocess.DEVNULL, timeout=300, check=True)
                self.after(0, self._check_auth_status)
                self._append_log("¡Cuenta de Google Drive autorizada con éxito!")
            except Exception as e:
                self._append_log(f"Error durante la autorización: {e}")
                self.after(0, self._check_auth_status)
                
        threading.Thread(target=_run_auth, daemon=True).start()

    def _check_auth_status(self):
        is_auth = self.rclone_mgr.is_remote_configured("gdrive")
        if is_auth:
            self.auth_status.configure(text="✓ Conectado a Google Drive", text_color="#4CAF50")
            self.btn_auth.configure(text="Re-conectar")
        else:
            self.auth_status.configure(text="✕ No Conectado a Google Drive", text_color="#F44336")
            self.btn_auth.configure(text="Conectar Cuenta")

    def _toggle_sync(self):
        self._save_form()
        if not self.worker._running:
            if not self.cfg.local_vault_path:
                self._append_log("⚠ Advertencia: Selecciona la ruta local de tu Vault de Obsidian antes de iniciar.")
                return
            vault_p = Path(self.cfg.local_vault_path).resolve()
            if not vault_p.is_dir():
                self._append_log(f"⚠ Error: La carpeta del Vault no existe o no es accesible: {self.cfg.local_vault_path}")
                return
            if vault_p == Path(vault_p.root) or vault_p == Path.home():
                self._append_log("⚠ Error de seguridad: No se permite sincronizar la raíz del sistema o la carpeta de usuario.")
                return
            self.worker.start()
            self.btn_toggle_sync.configure(text="Detener Sincronización", fg_color="#C62828", hover_color="#B71C1C")
            self._append_log("Daemon de sincronización iniciado.")
        else:
            self.worker.stop()
            self.btn_toggle_sync.configure(text="Iniciar Sincronización", fg_color="#2E7D32", hover_color="#1B5E20")
            self._append_log("Daemon de sincronización detenido.")

    def _sync_now(self):
        self._save_form()
        triggered = self.worker.trigger_now()
        if triggered:
            self._append_log("Sincronización manual solicitada.")
        else:
            self._append_log("Sincronización en curso o pausada; solicitud ignorada.")

    def _append_log(self, text: str):
        try:
            self.log_box.insert("end", f"{text}\n")
            self.log_box.see("end")
        except Exception:
            pass

    def on_worker_status_update(self, status: SyncStatus, msg: str):
        self.after(0, lambda: self._apply_worker_update(status, msg))

    def _apply_worker_update(self, status: SyncStatus, msg: str):
        color = STATUS_COLORS.get(status, "#FFFFFF")
        self.status_badge.configure(text=f"● {msg}", text_color=color)
        self._append_log(msg)

    def on_close_requested(self):
        self.withdraw()
