import time
from pathlib import Path
from unittest.mock import MagicMock, patch
from watchdog.events import FileModifiedEvent, DirModifiedEvent, FileMovedEvent
from src.core.vault_watcher import VaultChangeHandler, VaultWatcher

def test_vault_change_handler_should_ignore_rules():
    handler = VaultChangeHandler(callback=MagicMock(), debounce_seconds=1.0)
    
    # Exclusiones estrictas
    assert handler.should_ignore(".git") is True
    assert handler.should_ignore(".git/config") is True
    assert handler.should_ignore("subfolder/.git/index") is True
    assert handler.should_ignore(".gitignore") is True
    assert handler.should_ignore(".git-credentials") is True
    assert handler.should_ignore(".obsidian/workspace.json") is True
    assert handler.should_ignore(".obsidian/workspace-mobile.json") is True
    assert handler.should_ignore(".obsidian/cache/indexed.bin") is True
    assert handler.should_ignore("note.tmp") is True
    assert handler.should_ignore("note.txt~") is True
    assert handler.should_ignore("note.swp") is True
    assert handler.should_ignore(".obsidian/plugins/obsidian-git/data.json") is True

    # Windows backslash paths
    assert handler.should_ignore(".git\\config") is True
    assert handler.should_ignore(".obsidian\\workspace.json") is True
    assert handler.should_ignore("subfolder\\note.tmp") is True

    # Edge cases
    assert handler.should_ignore("") is True
    assert handler.should_ignore(None) is True

    # Archivos válidos que sí deben procesarse
    assert handler.should_ignore("MyNote.md") is False
    assert handler.should_ignore("folder/subnote.md") is False
    assert handler.should_ignore("assets/image.png") is False
    assert handler.should_ignore("books/doc.pdf") is False
    assert handler.should_ignore(".obsidian/app.json") is False
    assert handler.should_ignore(".obsidian/community-plugins.json") is False

def test_vault_change_handler_debounce_coalescing():
    callback = MagicMock()
    handler = VaultChangeHandler(callback=callback, debounce_seconds=0.1)

    # Simular ráfaga de 5 eventos seguidos
    for i in range(5):
        handler._on_valid_change()
        time.sleep(0.02)

    # Antes del tiempo de debounce no debe haber llamado
    assert callback.call_count == 0

    # Esperamos a que expire el debounce (0.1s + margen)
    time.sleep(0.15)
    assert callback.call_count == 1

def test_vault_watcher_cleanup_cancels_timer():
    callback = MagicMock()
    handler = VaultChangeHandler(callback=callback, debounce_seconds=0.1)
    handler._on_valid_change()
    assert handler._timer is not None

    handler.stop()
    assert handler._timer is None
    time.sleep(0.15)
    assert callback.call_count == 0

def test_vault_change_handler_on_any_event():
    callback = MagicMock()
    handler = VaultChangeHandler(callback=callback, debounce_seconds=0.1)

    # 1. Directory event ignored
    dir_event = DirModifiedEvent(src_path="/vault/folder")
    handler.on_any_event(dir_event)
    assert handler._timer is None

    # 2. Ignored file event ignored
    git_event = FileModifiedEvent(src_path="/vault/.git/index")
    handler.on_any_event(git_event)
    assert handler._timer is None

    # 3. FileMovedEvent to ignored destination ignored
    moved_to_ignored = FileMovedEvent(src_path="/vault/note.md", dest_path="/vault/.obsidian/workspace.json")
    handler.on_any_event(moved_to_ignored)
    assert handler._timer is None

    # 4. Valid file event schedules timer
    valid_event = FileModifiedEvent(src_path="/vault/Note.md")
    handler.on_any_event(valid_event)
    assert handler._timer is not None

    handler.stop()

def test_vault_change_handler_callback_exception_handled():
    def broken_callback():
        raise RuntimeError("Callback failed")

    handler = VaultChangeHandler(callback=broken_callback, debounce_seconds=0.05)
    handler._on_valid_change()
    time.sleep(0.1)
    # Shouldn't raise or leave running timer
    assert handler._timer is None

def test_vault_watcher_lifecycle(tmp_path):
    callback = MagicMock()
    watcher = VaultWatcher(callback=callback, debounce_seconds=1.0)
    assert watcher._running is False

    # Start with non-existent path
    watcher.start(str(tmp_path / "non_existent"))
    assert watcher._running is False

    # Start with valid path (patching Observer)
    with patch("src.core.vault_watcher.Observer") as MockObserver:
        mock_obs_instance = MagicMock()
        MockObserver.return_value = mock_obs_instance

        watcher.start(str(tmp_path))
        assert watcher._running is True
        mock_obs_instance.schedule.assert_called_once_with(watcher.handler, str(tmp_path.resolve()), recursive=True)
        mock_obs_instance.start.assert_called_once()

        # Stop
        watcher.stop()
        assert watcher._running is False
        mock_obs_instance.stop.assert_called_once()
        mock_obs_instance.join.assert_called_once_with(timeout=2)
