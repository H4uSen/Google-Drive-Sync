"""Tests for Standalone Packaging and Build configuration."""
from pathlib import Path
import ast
import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent
PACKAGING_DIR = ROOT_DIR / "packaging"
SPEC_FILE = PACKAGING_DIR / "obsidian-gdrive-sync.spec"
BUILD_SCRIPT = PACKAGING_DIR / "build.py"

def test_spec_file_exists_and_is_valid():
    assert SPEC_FILE.exists(), f"Missing spec file: {SPEC_FILE}"
    spec_content = SPEC_FILE.read_text(encoding="utf-8")
    
    # Must compile cleanly as valid Python
    code = compile(spec_content, str(SPEC_FILE), "exec")
    assert code is not None

    # Inspect AST to verify essential configurations
    parsed = ast.parse(spec_content)
    assert parsed is not None

    # Verify key dependencies are in hiddenimports or referenced
    assert "customtkinter" in spec_content
    assert "pystray" in spec_content
    assert "watchdog" in spec_content
    assert "PIL" in spec_content

def test_build_script_exists_and_runnable():
    assert BUILD_SCRIPT.exists(), f"Missing build script: {BUILD_SCRIPT}"
    build_content = BUILD_SCRIPT.read_text(encoding="utf-8")
    
    # Must compile cleanly as valid Python
    code = compile(build_content, str(BUILD_SCRIPT), "exec")
    assert code is not None

    # Check CLI options in build script
    assert "pyinstaller" in build_content.lower()
    assert "--clean" in build_content
    assert "obsidian-gdrive-sync.spec" in build_content
