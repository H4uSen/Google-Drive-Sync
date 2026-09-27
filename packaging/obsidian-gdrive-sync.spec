# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import sys
import customtkinter

block_cipher = None

# CustomTkinter assets directory
ctk_dir = Path(customtkinter.__file__).parent
datas = [
    (str(ctk_dir), 'customtkinter/'),
]

# Hidden imports needed for background tray, imaging, file watcher, and platform-specific modules
hiddenimports = [
    'customtkinter',
    'pystray',
    'pystray._util',
    'PIL',
    'PIL.Image',
    'PIL.ImageTk',
    'watchdog',
    'watchdog.observers',
    'watchdog.observers.api',
    'watchdog.events',
]

if sys.platform.startswith('linux'):
    hiddenimports.extend([
        'pystray._appindicator',
        'pystray._xorg',
        'watchdog.observers.inotify',
    ])
elif sys.platform.startswith('win'):
    hiddenimports.extend([
        'pystray._win32',
        'watchdog.observers.read_directory_changes',
        'winreg',
    ])

a = Analysis(
    ['../src/main.py'],
    pathex=['.'],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='obsidian-gdrive-sync',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
