"""FileWatcher — singleton inotify-backed file/directory watcher.

Replaces the 4 separate watchdog ``Observer`` instances used across the
application with a single ``Observer`` and a subscription-based API.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from threading import Lock as ThreadLock
from typing import Callable

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

logger = logging.getLogger(__name__)

# Callback signatures:
#   Directory: async def cb(event_type: str, file_path: str) -> None
#   File:      async def cb(event_type: str, file_path: str) -> None
# event_type is "created" | "modified" | "deleted"

DirCallback = Callable[[str, str], object]
FileCallback = Callable[[str, str], object]


class _Handler(FileSystemEventHandler):
    """Dispatch watchdog events to registered callbacks via the event loop."""

    def __init__(self, watcher: FileWatcher) -> None:
        super().__init__()
        self._watcher = watcher

    def on_created(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._watcher._dispatch(str(event.src_path), "created")

    def on_modified(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._watcher._dispatch(str(event.src_path), "modified")

    def on_deleted(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._watcher._dispatch(str(event.src_path), "deleted")


class FileWatcher:
    """Singleton inotify watcher with directory and file subscriptions.

    Thread-safe: watchdog callbacks run on a background thread and are
    bridged to the async event loop via ``asyncio.run_coroutine_threadsafe``.
    """

    _instance: FileWatcher | None = None

    @classmethod
    def get_instance(cls) -> FileWatcher:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Shut down and discard the singleton (for tests)."""
        if cls._instance is not None:
            cls._instance.shutdown()
            cls._instance = None

    def __init__(self) -> None:
        self._observer: Observer | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._handler = _Handler(self)

        # Thread lock protects all mutable state below (watchdog callbacks
        # arrive on a background thread).
        self._lock = ThreadLock()

        # Directory subscriptions: dir_path -> list of callbacks
        self._dir_subs: dict[str, list[DirCallback]] = {}

        # File subscriptions: file_path -> list of callbacks
        self._file_subs: dict[str, list[FileCallback]] = {}

        # Refcount per watched directory -> watchdog ObservedWatch handle
        self._dir_watches: dict[str, object] = {}  # dir_path -> ObservedWatch
        self._dir_refcount: dict[str, int] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def watch_directory(self, path: str, callback: DirCallback) -> None:
        """Subscribe to file events in a directory.

        On subscribe, enumerates existing files and awaits the callback with
        ``"created"`` for each (so the caller can discover pre-existing
        files before this method returns).
        """
        dir_path = str(Path(path).resolve())
        with self._lock:
            self._ensure_observer()

            subs = self._dir_subs.setdefault(dir_path, [])
            subs.append(callback)

            # Schedule the directory if this is the first subscriber
            if dir_path not in self._dir_watches:
                if Path(dir_path).is_dir():
                    watch = self._observer.schedule(  # type: ignore[union-attr]
                        self._handler, dir_path, recursive=False
                    )
                    self._dir_watches[dir_path] = watch
                    self._dir_refcount[dir_path] = 0
            self._dir_refcount[dir_path] = self._dir_refcount.get(dir_path, 0) + 1

        # Enumerate existing files (outside the lock to avoid blocking
        # the watchdog thread).  We await each callback directly since
        # we're on the event loop thread — no fire-and-forget.
        if Path(dir_path).is_dir():
            try:
                for entry in os.scandir(dir_path):
                    if entry.is_file():
                        await self._dispatch_initial(callback, "created", entry.path)
            except OSError:
                logger.debug("Failed to enumerate %s", dir_path)

    def unwatch_directory(self, path: str, callback: DirCallback) -> None:
        """Remove a directory subscription."""
        dir_path = str(Path(path).resolve())
        with self._lock:
            subs = self._dir_subs.get(dir_path)
            if subs is None:
                return
            try:
                subs.remove(callback)
            except ValueError:
                return

            count = self._dir_refcount.get(dir_path, 1) - 1
            self._dir_refcount[dir_path] = count

            if count <= 0:
                # No subscribers left — unschedule
                watch = self._dir_watches.pop(dir_path, None)
                self._dir_refcount.pop(dir_path, None)
                self._dir_subs.pop(dir_path, None)
                if watch is not None and self._observer is not None:
                    try:
                        self._observer.unschedule(watch)  # type: ignore[arg-type]
                    except Exception:
                        pass
                self._maybe_stop_observer()

    def watch_file(self, path: str, callback: FileCallback) -> None:
        """Subscribe to changes on a single file.

        Internally watches the parent directory and filters events.
        """
        file_path = str(Path(path).resolve())
        dir_path = str(Path(file_path).parent)
        with self._lock:
            self._ensure_observer()

            subs = self._file_subs.setdefault(file_path, [])
            subs.append(callback)

            # Watch the parent directory
            if dir_path not in self._dir_watches:
                if Path(dir_path).is_dir():
                    watch = self._observer.schedule(  # type: ignore[union-attr]
                        self._handler, dir_path, recursive=False
                    )
                    self._dir_watches[dir_path] = watch
                    self._dir_refcount[dir_path] = 0
            self._dir_refcount[dir_path] = self._dir_refcount.get(dir_path, 0) + 1

    def unwatch_file(self, path: str, callback: FileCallback) -> None:
        """Remove a file subscription."""
        file_path = str(Path(path).resolve())
        dir_path = str(Path(file_path).parent)
        with self._lock:
            subs = self._file_subs.get(file_path)
            if subs is None:
                return
            try:
                subs.remove(callback)
            except ValueError:
                return
            if not subs:
                del self._file_subs[file_path]

            count = self._dir_refcount.get(dir_path, 1) - 1
            self._dir_refcount[dir_path] = count

            if count <= 0:
                # Check if any directory-level subs still exist
                if dir_path not in self._dir_subs or not self._dir_subs[dir_path]:
                    watch = self._dir_watches.pop(dir_path, None)
                    self._dir_refcount.pop(dir_path, None)
                    if watch is not None and self._observer is not None:
                        try:
                            self._observer.unschedule(watch)  # type: ignore[arg-type]
                        except Exception:
                            pass
                    self._maybe_stop_observer()

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Set the event loop for async dispatch (call from main thread)."""
        self._loop = loop

    def shutdown(self) -> None:
        """Stop the observer and clear all subscriptions."""
        with self._lock:
            if self._observer is not None:
                try:
                    self._observer.stop()
                except Exception:
                    pass
                self._observer = None
            self._dir_subs.clear()
            self._file_subs.clear()
            self._dir_watches.clear()
            self._dir_refcount.clear()

    # ------------------------------------------------------------------
    # Internal dispatch (called from watchdog thread)
    # ------------------------------------------------------------------

    def _dispatch(self, file_path: str, event_type: str) -> None:
        """Route a watchdog event to matching subscribers."""
        dir_path = str(Path(file_path).parent)
        with self._lock:
            # Directory subscribers
            dir_cbs = list(self._dir_subs.get(dir_path, []))

            # File subscribers
            file_cbs = list(self._file_subs.get(file_path, []))

        for cb in dir_cbs:
            self._dispatch_single(cb, event_type, file_path)
        for cb in file_cbs:
            self._dispatch_single(cb, event_type, file_path)

    async def _dispatch_initial(
        self, callback: DirCallback | FileCallback, event_type: str, file_path: str
    ) -> None:
        """Dispatch a callback during initial enumeration (on the event loop thread).

        Unlike _dispatch_single (used by watchdog thread), this awaits
        async callbacks directly so the caller knows when they complete.
        """
        try:
            if asyncio.iscoroutinefunction(callback):
                await callback(event_type, file_path)  # type: ignore[misc]
            else:
                callback(event_type, file_path)  # type: ignore[call-arg]
        except Exception:
            logger.debug("Error in initial dispatch callback", exc_info=True)

    def _dispatch_single(
        self, callback: DirCallback | FileCallback, event_type: str, file_path: str
    ) -> None:
        """Dispatch a single callback from the watchdog thread, bridging to async."""
        loop = self._loop
        if loop is None:
            # Try to get the running loop
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                return

        if asyncio.iscoroutinefunction(callback):
            try:
                asyncio.run_coroutine_threadsafe(callback(event_type, file_path), loop)  # type: ignore[arg-type]
            except RuntimeError:
                pass
        else:
            # Synchronous callback — schedule on the loop to keep things orderly
            try:
                loop.call_soon_threadsafe(callback, event_type, file_path)
            except RuntimeError:
                pass

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_observer(self) -> None:
        """Start the observer if not running. Caller must hold self._lock."""
        if self._observer is None:
            self._observer = Observer()
            self._observer.daemon = True
            self._observer.start()

    def _maybe_stop_observer(self) -> None:
        """Stop observer if no subscriptions remain. Caller must hold self._lock."""
        has_dir_subs = any(bool(v) for v in self._dir_subs.values())
        has_file_subs = any(bool(v) for v in self._file_subs.values())
        if not has_dir_subs and not has_file_subs:
            if self._observer is not None:
                try:
                    self._observer.stop()
                except Exception:
                    pass
                self._observer = None
