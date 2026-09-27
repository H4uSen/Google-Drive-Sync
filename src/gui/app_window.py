import sys
import threading
import subprocess
from pathlib import Path
from tkinter import filedialog
import customtkinter as ctk
from src.core.config import ConfigManager, ConfigData
from src.core.sync_worker import SyncWorker, SyncStatus, COLOR_MAP
from src.core.rclone_manager import RcloneManager
from src.utils.autostart import set_autostart, is_autostart_enabled

STATUS_COLORS = COLOR_MAP

class MainWindow(ctk.CTk):
    def __init__(self, config_manager: ConfigManager, worker: SyncWorker, rclone_mgr: RcloneManager):
        super().__init__()
        self.config_mgr = config_manager
        self.worker = worker
        self.rclone_mgr = rclone_mgr
        self.cfg = self.config_mgr.load()
        self.chk_realtime = None
        self.entry_debounce = None
        self.quota_bar = None
        self.quota_label = None
        self.quota_container = None

        if "tk" not in self.__dict__:
            self.tk = None
            return

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

        self.auth_top_row = ctk.CTkFrame(self.auth_frame, fg_color="transparent")
        self.auth_top_row.pack(fill="x", padx=16, pady=(12, 6))

        self.auth_status = ctk.CTkLabel(
            self.auth_top_row,
            text="Google Drive: Comprobando conexión...",
            font=ctk.CTkFont(size=13)
        )
        self.auth_status.pack(side="left")

        self.btn_auth = ctk.CTkButton(
            self.auth_top_row,
            text="Conectar Cuenta",
            command=self._handle_auth,
            width=140
        )
        self.btn_auth.pack(side="right")

        # Contenedor de Cuota
        self.quota_container = ctk.CTkFrame(self.auth_frame, fg_color="transparent")
        self.quota_label = ctk.CTkLabel(
            self.quota_container,
            text="",
            font=ctk.CTkFont(size=11),
            text_color="#B0BEC5"
        )
        self.quota_label.pack(anchor="w")
        self.quota_bar = ctk.CTkProgressBar(self.quota_container, height=6)
        self.quota_bar.set(0)
        self.quota_bar.pack(fill="x", pady=(2, 10))

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

        # Checkbox Iniciar con el sistema
        self.chk_autostart = ctk.CTkCheckBox(
            self.form_frame,
            text="Iniciar automáticamente con el sistema",
            command=self._on_toggle_autostart,
            font=ctk.CTkFont(size=13)
        )
        self.chk_autostart.grid(row=6, column=0, columnspan=2, padx=16, pady=(4, 8), sticky="w")
        if is_autostart_enabled():
            self.chk_autostart.select()
        else:
            self.chk_autostart.deselect()

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
        self.entry_debounce.bind("<FocusOut>", lambda _: self._save_form())

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
        except (ValueError, AttributeError):
            interval = 2
        if hasattr(self, "entry_local") and self.entry_local is not None:
            self.cfg.local_vault_path = self.entry_local.get().strip()

        if hasattr(self, "entry_remote") and self.entry_remote is not None:
            raw_remote = self.entry_remote.get().strip().strip("/\\").replace("\\", "/")
            parts = [p for p in raw_remote.split("/") if p]
            if not raw_remote or raw_remote == "." or ".." in parts:
                raw_remote = "ObsidianVault"
            self.cfg.remote_folder_name = raw_remote

        self.cfg.sync_interval_minutes = max(1, interval)

        try:
            debounce = int(self.entry_debounce.get())
        except (ValueError, AttributeError):
            debounce = 5
        self.cfg.debounce_delay_seconds = max(1, min(60, debounce))

        if hasattr(self, "chk_realtime") and self.chk_realtime is not None:
            self.cfg.realtime_sync_enabled = bool(self.chk_realtime.get())

        self.config_mgr.save(self.cfg)
        self.worker.config = self.cfg

        # Actualizar watcher en caliente si el worker está activo
        if getattr(self.worker, "_running", False):
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
            self._refresh_storage_quota()
        else:
            self.auth_status.configure(text="✕ No Conectado a Google Drive", text_color="#F44336")
            self.btn_auth.configure(text="Conectar Cuenta")
            self._apply_quota_data(None)

    def _refresh_storage_quota(self):
        def _fetch():
            quota = self.rclone_mgr.get_storage_quota("gdrive")
            try:
                if getattr(self, "tk", None):
                    self.after(0, lambda: self._apply_quota_data(quota))
            except Exception:
                pass
        threading.Thread(target=_fetch, daemon=True).start()

    def _apply_quota_data(self, quota: dict | None):
        if not hasattr(self, "quota_bar") or not hasattr(self, "quota_label"):
            return
        if not quota:
            if getattr(self, "quota_container", None) and hasattr(self.quota_container, "pack_forget"):
                self.quota_container.pack_forget()
            return

        percent = quota.get("percent", 0.0)
        used_s = quota.get("used_str", "")
        tot_s = quota.get("total_str", "")
        pct_s = quota.get("percent_str", "")

        if percent > 0.90:
            color = "#F44336"
        elif percent > 0.75:
            color = "#FFC107"
        else:
            color = "#4CAF50"

        if getattr(self, "quota_bar", None) and hasattr(self.quota_bar, "set"):
            self.quota_bar.set(percent)
            if hasattr(self.quota_bar, "configure"):
                self.quota_bar.configure(progress_color=color)
        if getattr(self, "quota_label", None) and hasattr(self.quota_label, "configure"):
            self.quota_label.configure(
                text=f"Almacenamiento: {used_s} / {tot_s} ({pct_s})"
            )
        if getattr(self, "quota_container", None) and hasattr(self.quota_container, "pack"):
            self.quota_container.pack(fill="x", padx=16, pady=(0, 10))

    def _on_toggle_autostart(self):
        enabled = bool(self.chk_autostart.get())
        success = set_autostart(enabled)
        if success:
            self.cfg.autostart_enabled = enabled
            self.config_mgr.save(self.cfg)
            msg = "Inicio automático activado." if enabled else "Inicio automático desactivado."
            self._append_log(msg)
        else:
            self._append_log("⚠ No se pudo actualizar la configuración de inicio automático en el sistema.")
            if is_autostart_enabled():
                self.chk_autostart.select()
            else:
                self.chk_autostart.deselect()

    def can_auto_start_sync(self) -> bool:
        if not self.cfg.local_vault_path:
            return False
        vault_p = Path(self.cfg.local_vault_path).resolve()
        if not vault_p.is_dir() or vault_p == Path(vault_p.anchor) or vault_p == Path.home():
            return False
        return self.rclone_mgr.is_remote_configured("gdrive")

    def start_sync_engine(self) -> bool:
        if not self.worker._running:
            if not self.can_auto_start_sync():
                return False
            self.worker.start()
            self.btn_toggle_sync.configure(text="Detener Sincronización", fg_color="#C62828", hover_color="#B71C1C")
            self._append_log("Daemon de sincronización iniciado.")
            return True
        return False

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
            if vault_p == Path(vault_p.anchor) or vault_p == Path.home():
                self._append_log("⚠ Error de seguridad: No se permite sincronizar la raíz del sistema o la carpeta de usuario.")
                return
            self.start_sync_engine()
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
