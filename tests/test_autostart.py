"""Tests for autostart helper."""
from pathlib import Path
from src.utils.autostart import generate_linux_desktop_entry

def test_generate_linux_desktop_entry():
    content = generate_linux_desktop_entry("/usr/bin/obsidian-sync")
    assert "[Desktop Entry]" in content
    assert "Exec=/usr/bin/obsidian-sync --minimized" in content
    assert "Type=Application" in content
    assert "Name=Obsidian GDrive Sync" in content
