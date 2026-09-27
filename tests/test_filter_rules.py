"""Tests for filter rules generator."""
from pathlib import Path
from src.core.rclone_manager import DEFAULT_FILTER_RULES, write_filters_file

def test_default_rules_contain_git_and_obsidian_exclusions():
    rules = DEFAULT_FILTER_RULES
    assert "- .git/**" in rules
    assert "- .gitignore" in rules
    assert "- .obsidian/workspace.json" in rules
    assert "- .obsidian/workspace-mobile.json" in rules
    assert "- .obsidian/cache/**" in rules
    assert "+ *" in rules

def test_write_filters_file(tmp_path):
    filter_file = tmp_path / "filters.txt"
    written = write_filters_file(filter_file)
    assert written.exists()
    content = written.read_text(encoding="utf-8")
    assert "- .git/**" in content
    assert "+ *" in content
