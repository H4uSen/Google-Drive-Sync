import sys
import stat
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest
from src.utils.autostart import (
    is_autostart_supported,
    get_autostart_command,
    set_autostart,
    is_autostart_enabled,
    get_linux_desktop_file_path,
    get_linux_autostart_dir,
)

def test_autostart_supported_on_linux_and_windows():
    assert is_autostart_supported() in (True, False)

def test_linux_autostart_command_format():
    cmd = get_autostart_command()
    assert "--minimized" in cmd
    assert "src.main" in cmd

def test_linux_set_autostart_lifecycle(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "linux")
    fake_autostart = tmp_path / "autostart"
    monkeypatch.setattr("src.utils.autostart.get_linux_autostart_dir", lambda: fake_autostart)

    assert is_autostart_enabled() is False

    # Activar
    assert set_autostart(True) is True
    desktop_file = fake_autostart / "obsidian-gdrive-sync.desktop"
    assert desktop_file.exists()
    content = desktop_file.read_text(encoding="utf-8")
    assert "[Desktop Entry]" in content
    assert "--minimized" in content
    assert is_autostart_enabled() is True

    # Check restrictive file permissions on linux
    file_mode = stat.S_IMODE(desktop_file.stat().st_mode)
    assert file_mode == 0o700

    # Idempotencia al activar de nuevo
    assert set_autostart(True) is True
    assert is_autostart_enabled() is True

    # Desactivar
    assert set_autostart(False) is True
    assert not desktop_file.exists()
    assert is_autostart_enabled() is False

    # Idempotencia al desactivar de nuevo
    assert set_autostart(False) is True

def test_linux_autostart_dir_permissions(monkeypatch, tmp_path):
    fake_config = tmp_path / "custom_config"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(fake_config))
    monkeypatch.setattr(sys, "platform", "linux")
    autostart_dir = get_linux_autostart_dir()
    assert autostart_dir.is_dir()
    mode = stat.S_IMODE(autostart_dir.stat().st_mode)
    assert mode == 0o700

def test_windows_set_autostart_lifecycle(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    mock_winreg = MagicMock()
    monkeypatch.setitem(sys.modules, "winreg", mock_winreg)

    # Simular lectura exitosa
    mock_winreg.OpenKey.return_value = MagicMock()
    mock_winreg.QueryValueEx.return_value = ('"pythonw.exe" -m src.main --minimized', 1)

    assert is_autostart_enabled() is True

    # Desactivar
    assert set_autostart(False) is True
    mock_winreg.DeleteValue.assert_called_once()

def test_windows_set_autostart_enable(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    mock_winreg = MagicMock()
    monkeypatch.setitem(sys.modules, "winreg", mock_winreg)

    key_mock = MagicMock()
    mock_winreg.OpenKey.return_value = key_mock

    assert set_autostart(True) is True
    mock_winreg.SetValueEx.assert_called_once()
    args = mock_winreg.SetValueEx.call_args[0]
    assert args[1] == "ObsidianGDriveSync"
    assert "--minimized" in args[4]

def test_windows_is_autostart_enabled_not_found(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    mock_winreg = MagicMock()
    mock_winreg.OpenKey.side_effect = FileNotFoundError()
    monkeypatch.setitem(sys.modules, "winreg", mock_winreg)

    assert is_autostart_enabled() is False

def test_unsupported_platform(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    assert is_autostart_supported() is False
    assert set_autostart(True) is False
    assert is_autostart_enabled() is False

def test_windows_pythonw_fallback(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "win32")
    fake_python = tmp_path / "python.exe"
    fake_python.touch()
    monkeypatch.setattr(sys, "executable", str(fake_python))

    cmd = get_autostart_command()
    assert str(fake_python) in cmd

    # When pythonw exists
    fake_pythonw = tmp_path / "pythonw.exe"
    fake_pythonw.touch()
    cmd2 = get_autostart_command()
    assert str(fake_pythonw) in cmd2

def test_linux_set_autostart_error_handling(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    with patch("src.utils.autostart.get_linux_desktop_file_path") as mock_path:
        mock_file = MagicMock()
        mock_file.write_text.side_effect = PermissionError("Permission denied")
        mock_path.return_value = mock_file
        assert set_autostart(True) is False

    with patch("src.utils.autostart.get_linux_desktop_file_path") as mock_path:
        mock_file = MagicMock()
        mock_file.unlink.side_effect = PermissionError("Permission denied")
        mock_path.return_value = mock_file
        assert set_autostart(False) is False

def test_windows_set_autostart_error_handling(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    mock_winreg = MagicMock()
    mock_winreg.OpenKey.side_effect = PermissionError("Access denied")
    monkeypatch.setitem(sys.modules, "winreg", mock_winreg)
    assert set_autostart(True) is False

