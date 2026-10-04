"""
Unit tests for core event messaging system (EventDispatcher, EventType, typed payloads).
"""
import threading
import time
import pytest
from src.core.events import (
    EventDispatcher,
    EventType,
    Event,
    StatusPayload,
    ProgressPayload,
    FilePayload,
    ConflictPayload,
    BatchPayload,
    LogPayload,
    get_dispatcher,
    reset_dispatcher,
)


class TestEventTaxonomyAndPayloads:
    def test_event_type_members(self):
        expected_types = {
            "STATUS_CHANGED",
            "PROGRESS_UPDATED",
            "FILE_TRANSFERRED",
            "CONFLICT_DETECTED",
            "BATCH_COMPLETED",
            "LOG_EMITTED",
        }
        actual_types = {e.name for e in EventType}
        assert expected_types.issubset(actual_types)

    def test_status_payload_instantiation(self):
        payload = StatusPayload(status="idle", message="Sistema listo", vault_name="/vault")
        assert payload.status == "idle"
        assert payload.message == "Sistema listo"
        assert payload.vault_name == "/vault"

    def test_progress_payload_instantiation(self):
        payload = ProgressPayload(
            transferred_bytes=1024,
            total_bytes=4096,
            percentage=25.0,
            speed_str="1.5 MB/s",
            current_file="doc.md",
            eta_str="2s",
        )
        assert payload.transferred_bytes == 1024
        assert payload.total_bytes == 4096
        assert payload.percentage == 25.0
        assert payload.speed_str == "1.5 MB/s"
        assert payload.current_file == "doc.md"
        assert payload.eta_str == "2s"

    def test_file_payload_instantiation(self):
        payload = FilePayload(
            filename="notes/todo.md",
            size=512,
            action="Copied (new)",
            vault_name="/vault",
        )
        assert payload.filename == "notes/todo.md"
        assert payload.size == 512
        assert payload.action == "Copied (new)"
        assert payload.vault_name == "/vault"

    def test_conflict_payload_instantiation(self):
        payload = ConflictPayload(
            filename="conflict.md",
            details="md5 differ",
            local_path="/vault/conflict.md",
            remote_path="gdrive:vault/conflict.md",
        )
        assert payload.filename == "conflict.md"
        assert payload.details == "md5 differ"
        assert payload.local_path == "/vault/conflict.md"
        assert payload.remote_path == "gdrive:vault/conflict.md"

    def test_batch_payload_instantiation(self):
        payload = BatchPayload(
            total_files=5,
            total_bytes=10000,
            elapsed_seconds=3.2,
            files=["a.md", "b.md"],
            status="SUCCESS",
        )
        assert payload.total_files == 5
        assert payload.total_bytes == 10000
        assert payload.elapsed_seconds == 3.2
        assert payload.files == ["a.md", "b.md"]
        assert payload.status == "SUCCESS"

    def test_log_payload_instantiation(self):
        now = time.time()
        payload = LogPayload(level="INFO", message="Sync started", timestamp=now, logger_name="sync")
        assert payload.level == "INFO"
        assert payload.message == "Sync started"
        assert payload.timestamp == now
        assert payload.logger_name == "sync"

    def test_event_envelope(self):
        t_before = time.time()
        event = Event(event_type=EventType.STATUS_CHANGED, data={"key": "val"})
        t_after = time.time()
        assert event.event_type == EventType.STATUS_CHANGED
        assert event.data == {"key": "val"}
        assert t_before <= event.timestamp <= t_after


class TestEventDispatcherSubscription:
    def test_subscribe_and_emit_single_listener(self):
        dispatcher = EventDispatcher()
        received = []

        def listener(ev: Event):
            received.append(ev)

        dispatcher.subscribe(EventType.STATUS_CHANGED, listener)
        payload = StatusPayload(status="syncing", message="Sincronizando")
        dispatcher.emit(EventType.STATUS_CHANGED, payload)

        assert len(received) == 1
        assert received[0].event_type == EventType.STATUS_CHANGED
        assert received[0].data == payload

    def test_subscribe_multiple_listeners(self):
        dispatcher = EventDispatcher()
        calls = []

        def listener_a(ev: Event):
            calls.append("A")

        def listener_b(ev: Event):
            calls.append("B")

        dispatcher.subscribe(EventType.FILE_TRANSFERRED, listener_a)
        dispatcher.subscribe(EventType.FILE_TRANSFERRED, listener_b)

        dispatcher.emit(EventType.FILE_TRANSFERRED, FilePayload("f.txt", 100))
        assert calls == ["A", "B"]

    def test_event_filtering_isolation(self):
        dispatcher = EventDispatcher()
        status_events = []
        progress_events = []

        dispatcher.subscribe(EventType.STATUS_CHANGED, lambda ev: status_events.append(ev))
        dispatcher.subscribe(EventType.PROGRESS_UPDATED, lambda ev: progress_events.append(ev))

        dispatcher.emit(EventType.STATUS_CHANGED, StatusPayload("idle", "Listo"))

        assert len(status_events) == 1
        assert len(progress_events) == 0

    def test_duplicate_subscription_prevented(self):
        dispatcher = EventDispatcher()
        calls = []

        def listener(ev: Event):
            calls.append(1)

        dispatcher.subscribe(EventType.STATUS_CHANGED, listener)
        dispatcher.subscribe(EventType.STATUS_CHANGED, listener)
        assert dispatcher.subscriber_count(EventType.STATUS_CHANGED) == 1

        dispatcher.emit(EventType.STATUS_CHANGED, "msg")
        assert len(calls) == 1

    def test_subscribe_non_callable_raises_type_error(self):
        dispatcher = EventDispatcher()
        with pytest.raises(TypeError, match="must be callable"):
            dispatcher.subscribe(EventType.STATUS_CHANGED, "not_a_function")  # type: ignore

        with pytest.raises(TypeError, match="must be callable"):
            dispatcher.subscribe_all("not_a_function")  # type: ignore

    def test_unsubscribe_removes_listener(self):
        dispatcher = EventDispatcher()
        calls = []

        def listener(ev: Event):
            calls.append(1)

        dispatcher.subscribe(EventType.STATUS_CHANGED, listener)
        dispatcher.emit(EventType.STATUS_CHANGED, "first")
        assert len(calls) == 1

        dispatcher.unsubscribe(EventType.STATUS_CHANGED, listener)
        dispatcher.emit(EventType.STATUS_CHANGED, "second")
        assert len(calls) == 1
        assert dispatcher.subscriber_count(EventType.STATUS_CHANGED) == 0

    def test_unsubscribe_nonexistent_listener_is_noop(self):
        dispatcher = EventDispatcher()
        def dummy(ev: Event): pass
        # Should not raise any error
        dispatcher.unsubscribe(EventType.STATUS_CHANGED, dummy)
        dispatcher.unsubscribe_all(dummy)

    def test_wildcard_subscription(self):
        dispatcher = EventDispatcher()
        received = []

        def wildcard(ev: Event):
            received.append(ev.event_type)

        dispatcher.subscribe_all(wildcard)
        dispatcher.emit(EventType.STATUS_CHANGED, "s")
        dispatcher.emit(EventType.PROGRESS_UPDATED, "p")
        dispatcher.emit(EventType.FILE_TRANSFERRED, "f")

        assert received == [
            EventType.STATUS_CHANGED,
            EventType.PROGRESS_UPDATED,
            EventType.FILE_TRANSFERRED,
        ]

    def test_unsubscribe_all(self):
        dispatcher = EventDispatcher()
        calls = []

        def handler(ev: Event):
            calls.append(ev.event_type)

        dispatcher.subscribe(EventType.STATUS_CHANGED, handler)
        dispatcher.subscribe(EventType.FILE_TRANSFERRED, handler)
        dispatcher.subscribe_all(handler)

        dispatcher.unsubscribe_all(handler)
        dispatcher.emit(EventType.STATUS_CHANGED, "s")
        dispatcher.emit(EventType.FILE_TRANSFERRED, "f")

        assert len(calls) == 0

    def test_clear_removes_all_subscribers(self):
        dispatcher = EventDispatcher()
        dispatcher.subscribe(EventType.STATUS_CHANGED, lambda ev: None)
        dispatcher.subscribe_all(lambda ev: None)
        assert dispatcher.subscriber_count() == 2

        dispatcher.clear()
        assert dispatcher.subscriber_count() == 0


class TestEventDispatcherErrorBoundaries:
    def test_listener_exception_does_not_crash_emitter(self):
        dispatcher = EventDispatcher()

        def broken_listener(ev: Event):
            raise ZeroDivisionError("Simulated listener crash")

        dispatcher.subscribe(EventType.STATUS_CHANGED, broken_listener)
        # emit must NOT raise exception
        dispatcher.emit(EventType.STATUS_CHANGED, StatusPayload("error", "fallo"))

    def test_failing_listener_does_not_block_subsequent_listeners(self):
        dispatcher = EventDispatcher()
        executed = []

        def fail_1(ev: Event):
            raise RuntimeError("Failure 1")

        def succeed(ev: Event):
            executed.append("success")

        def fail_2(ev: Event):
            raise ValueError("Failure 2")

        dispatcher.subscribe(EventType.STATUS_CHANGED, fail_1)
        dispatcher.subscribe(EventType.STATUS_CHANGED, succeed)
        dispatcher.subscribe(EventType.STATUS_CHANGED, fail_2)

        dispatcher.emit(EventType.STATUS_CHANGED, "data")
        assert executed == ["success"]


class TestEventDispatcherConcurrencyAndReentrancy:
    def test_reentrant_unsubscribe_inside_callback(self):
        dispatcher = EventDispatcher()
        calls = 0

        def self_unsubscribing(ev: Event):
            nonlocal calls
            calls += 1
            dispatcher.unsubscribe(EventType.STATUS_CHANGED, self_unsubscribing)

        dispatcher.subscribe(EventType.STATUS_CHANGED, self_unsubscribing)
        dispatcher.emit(EventType.STATUS_CHANGED, "1")
        dispatcher.emit(EventType.STATUS_CHANGED, "2")

        assert calls == 1

    def test_reentrant_subscribe_inside_callback(self):
        dispatcher = EventDispatcher()
        child_calls = []

        def child_cb(ev: Event):
            child_calls.append("child")

        def parent_cb(ev: Event):
            dispatcher.subscribe(EventType.STATUS_CHANGED, child_cb)

        dispatcher.subscribe(EventType.STATUS_CHANGED, parent_cb)
        dispatcher.emit(EventType.STATUS_CHANGED, "first")
        assert len(child_calls) == 0

        # On second emit, child_cb should receive event
        dispatcher.emit(EventType.STATUS_CHANGED, "second")
        assert child_calls == ["child"]

    def test_reentrant_emit_inside_callback(self):
        dispatcher = EventDispatcher()
        audit_trail = []

        def on_status(ev: Event):
            audit_trail.append(f"status:{ev.data}")
            if ev.data == "start":
                dispatcher.emit(EventType.PROGRESS_UPDATED, "50%")

        def on_progress(ev: Event):
            audit_trail.append(f"progress:{ev.data}")

        dispatcher.subscribe(EventType.STATUS_CHANGED, on_status)
        dispatcher.subscribe(EventType.PROGRESS_UPDATED, on_progress)

        dispatcher.emit(EventType.STATUS_CHANGED, "start")
        assert audit_trail == ["status:start", "progress:50%"]

    def test_concurrent_emit_thread_safety(self):
        dispatcher = EventDispatcher()
        counter = [0]
        lock = threading.Lock()

        def on_progress(ev: Event):
            with lock:
                counter[0] += 1

        dispatcher.subscribe(EventType.PROGRESS_UPDATED, on_progress)

        num_threads = 8
        emits_per_thread = 200

        def worker():
            for _ in range(emits_per_thread):
                dispatcher.emit(
                    EventType.PROGRESS_UPDATED,
                    ProgressPayload(transferred_bytes=100, total_bytes=1000, percentage=10.0),
                )

        threads = [threading.Thread(target=worker) for _ in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert counter[0] == num_threads * emits_per_thread

    def test_concurrent_subscribe_unsubscribe_emit(self):
        dispatcher = EventDispatcher()
        running = True
        errors = []

        def subscriber_thread():
            while running:
                def temp_cb(ev: Event): pass
                try:
                    dispatcher.subscribe(EventType.FILE_TRANSFERRED, temp_cb)
                    time.sleep(0.001)
                    dispatcher.unsubscribe(EventType.FILE_TRANSFERRED, temp_cb)
                except Exception as e:
                    errors.append(e)

        def emitter_thread():
            while running:
                try:
                    dispatcher.emit(EventType.FILE_TRANSFERRED, FilePayload("file.md", 100))
                    time.sleep(0.001)
                except Exception as e:
                    errors.append(e)

        threads = [
            threading.Thread(target=subscriber_thread),
            threading.Thread(target=subscriber_thread),
            threading.Thread(target=emitter_thread),
            threading.Thread(target=emitter_thread),
        ]
        for t in threads:
            t.start()

        time.sleep(0.15)
        running = False

        for t in threads:
            t.join()

        assert len(errors) == 0


class TestGlobalDispatcherHelpers:
    def test_get_and_reset_dispatcher(self):
        reset_dispatcher()
        d1 = get_dispatcher()
        d2 = get_dispatcher()
        assert d1 is d2
        assert isinstance(d1, EventDispatcher)

        reset_dispatcher()
        d3 = get_dispatcher()
        assert d3 is not d1
