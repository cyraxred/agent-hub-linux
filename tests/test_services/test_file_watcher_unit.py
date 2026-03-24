"""Unit tests for FileWatcher singleton."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent_hub.services.file_watcher import FileWatcher


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Ensure each test gets a clean singleton."""
    FileWatcher.reset_instance()
    yield
    FileWatcher.reset_instance()


class TestFileWatcherSingleton:
    def test_get_instance_returns_singleton(self):
        a = FileWatcher.get_instance()
        b = FileWatcher.get_instance()
        assert a is b

    def test_reset_instance_creates_new(self):
        a = FileWatcher.get_instance()
        FileWatcher.reset_instance()
        b = FileWatcher.get_instance()
        assert a is not b

    def test_set_loop(self):
        fw = FileWatcher.get_instance()
        loop = asyncio.new_event_loop()
        try:
            fw.set_loop(loop)
            assert fw._loop is loop
        finally:
            loop.close()


class TestFileWatcherDirectoryWatch:
    async def test_watch_directory_calls_schedule(self, tmp_path: Path):
        fw = FileWatcher()
        with patch.object(fw, "_ensure_observer"):
            fw._observer = MagicMock()
            fw._observer.schedule.return_value = MagicMock()
            cb = MagicMock()

            await fw.watch_directory(str(tmp_path), cb)

            fw._observer.schedule.assert_called_once()
            args = fw._observer.schedule.call_args
            assert str(tmp_path) in str(args)

        fw.shutdown()

    async def test_unwatch_directory_decrements_refcount(self, tmp_path: Path):
        fw = FileWatcher()
        fw._observer = MagicMock()
        fw._observer.schedule.return_value = MagicMock()

        cb1 = MagicMock()
        cb2 = MagicMock()

        dir_path = str(tmp_path.resolve())

        # Add two subscribers
        with patch.object(fw, "_ensure_observer"):
            await fw.watch_directory(dir_path, cb1)
            await fw.watch_directory(dir_path, cb2)

        assert fw._dir_refcount.get(dir_path) == 2

        # Remove one — should still be scheduled
        fw.unwatch_directory(dir_path, cb1)
        assert fw._dir_refcount.get(dir_path) == 1
        assert dir_path in fw._dir_watches

        # Remove second — should unschedule
        fw.unwatch_directory(dir_path, cb2)
        assert dir_path not in fw._dir_watches

        fw.shutdown()

    async def test_multiple_subscribers_same_directory(self, tmp_path: Path):
        fw = FileWatcher()
        fw._observer = MagicMock()
        fw._observer.schedule.return_value = MagicMock()

        cb1 = MagicMock()
        cb2 = MagicMock()

        dir_path = str(tmp_path.resolve())
        with patch.object(fw, "_ensure_observer"):
            await fw.watch_directory(dir_path, cb1)
            await fw.watch_directory(dir_path, cb2)

        # schedule should only be called once (first subscriber)
        assert fw._observer.schedule.call_count == 1
        assert fw._dir_refcount[dir_path] == 2

        # Both callbacks should be in the subscriber list
        assert cb1 in fw._dir_subs[dir_path]
        assert cb2 in fw._dir_subs[dir_path]

        fw.shutdown()

    async def test_initial_enumerate_fires_created(self, tmp_path: Path):
        """On watch_directory, existing files get 'created' callback awaited directly."""
        (tmp_path / "a.jsonl").write_text("{}")
        (tmp_path / "b.jsonl").write_text("{}")

        fw = FileWatcher()
        fw._observer = MagicMock()
        fw._observer.schedule.return_value = MagicMock()

        received: list[tuple[str, str]] = []

        async def cb(event_type: str, file_path: str) -> None:
            received.append((event_type, file_path))

        with patch.object(fw, "_ensure_observer"):
            await fw.watch_directory(str(tmp_path), cb)

        # Callbacks are awaited directly — no need to drain the loop
        created_paths = {fp for et, fp in received if et == "created"}
        assert str(tmp_path / "a.jsonl") in created_paths
        assert str(tmp_path / "b.jsonl") in created_paths

        fw.shutdown()


class TestFileWatcherFileWatch:
    def test_watch_file_creates_parent_watch(self, tmp_path: Path):
        fw = FileWatcher()
        fw._observer = MagicMock()
        fw._observer.schedule.return_value = MagicMock()

        test_file = tmp_path / "test.jsonl"
        test_file.write_text("{}")

        cb = MagicMock()
        with patch.object(fw, "_ensure_observer"):
            fw.watch_file(str(test_file), cb)

        dir_path = str(tmp_path.resolve())
        assert dir_path in fw._dir_watches
        assert str(test_file.resolve()) in fw._file_subs

        fw.shutdown()

    def test_unwatch_file_removes_subscription(self, tmp_path: Path):
        fw = FileWatcher()
        fw._observer = MagicMock()
        fw._observer.schedule.return_value = MagicMock()

        test_file = tmp_path / "test.jsonl"
        test_file.write_text("{}")

        cb = MagicMock()
        file_path = str(test_file.resolve())

        with patch.object(fw, "_ensure_observer"):
            fw.watch_file(str(test_file), cb)

        assert file_path in fw._file_subs

        fw.unwatch_file(str(test_file), cb)
        assert file_path not in fw._file_subs

        fw.shutdown()


class TestFileWatcherDispatch:
    def test_on_modified_dispatches_to_file_subscribers(self, tmp_path: Path):
        fw = FileWatcher()
        fw._observer = MagicMock()
        fw._observer.schedule.return_value = MagicMock()

        test_file = tmp_path / "test.jsonl"
        test_file.write_text("{}")
        file_path = str(test_file.resolve())

        received: list[tuple[str, str]] = []

        def cb(event_type: str, fp: str) -> None:
            received.append((event_type, fp))

        loop = asyncio.new_event_loop()
        fw.set_loop(loop)

        with patch.object(fw, "_ensure_observer"):
            fw.watch_file(str(test_file), cb)

        # Simulate a watchdog modified event
        fw._dispatch(file_path, "modified")

        # Sync callback dispatched via loop.call_soon_threadsafe
        loop.run_until_complete(asyncio.sleep(0))

        assert any(et == "modified" for et, _ in received)

        fw.shutdown()
        loop.close()

    async def test_on_created_dispatches_to_directory_subscribers(self, tmp_path: Path):
        fw = FileWatcher()
        fw._observer = MagicMock()
        fw._observer.schedule.return_value = MagicMock()

        received: list[tuple[str, str]] = []

        def cb(event_type: str, fp: str) -> None:
            received.append((event_type, fp))

        loop = asyncio.get_event_loop()
        fw.set_loop(loop)

        with patch.object(fw, "_ensure_observer"):
            await fw.watch_directory(str(tmp_path), cb)

        # Clear initial enumerate events
        received.clear()

        # Simulate new file created (from watchdog thread)
        fw._dispatch(str(tmp_path / "new.jsonl"), "created")

        await asyncio.sleep(0)
        new_file = str(tmp_path / "new.jsonl")
        assert any(et == "created" and fp == new_file for et, fp in received)

        fw.shutdown()

    async def test_on_deleted_dispatches_to_directory_subscribers(self, tmp_path: Path):
        fw = FileWatcher()
        fw._observer = MagicMock()
        fw._observer.schedule.return_value = MagicMock()

        received: list[tuple[str, str]] = []

        def cb(event_type: str, fp: str) -> None:
            received.append((event_type, fp))

        loop = asyncio.get_event_loop()
        fw.set_loop(loop)

        with patch.object(fw, "_ensure_observer"):
            await fw.watch_directory(str(tmp_path), cb)

        received.clear()

        deleted_file = str(tmp_path / "gone.jsonl")
        fw._dispatch(deleted_file, "deleted")

        await asyncio.sleep(0)
        assert any(et == "deleted" and fp == deleted_file for et, fp in received)

        fw.shutdown()


class TestFileWatcherShutdown:
    def test_shutdown_stops_observer(self):
        fw = FileWatcher()
        mock_observer = MagicMock()
        fw._observer = mock_observer

        fw.shutdown()

        mock_observer.stop.assert_called_once()
        assert fw._observer is None
        assert len(fw._dir_subs) == 0
        assert len(fw._file_subs) == 0
