"""Process registry — PID tracking, persistent PTY drain, and cleanup."""

from __future__ import annotations

import asyncio
import collections
import logging
import os
import signal
from typing import Callable

from agent_hub.services.terminal_launcher import TerminalProcess

logger = logging.getLogger(__name__)

_READ_CHUNK_SIZE = 4096

# Keep the last 64 KB of raw PTY output per process for reconnect replay.
_RING_BUFFER_MAX = 64 * 1024


class _RingBuffer:
    """Fixed-capacity byte ring buffer backed by a deque of chunks."""

    def __init__(self, max_bytes: int = _RING_BUFFER_MAX) -> None:
        self._max = max_bytes
        self._chunks: collections.deque[bytes] = collections.deque()
        self._size = 0

    def append(self, data: bytes) -> None:
        self._chunks.append(data)
        self._size += len(data)
        while self._size > self._max and self._chunks:
            removed = self._chunks.popleft()
            self._size -= len(removed)

    def snapshot(self) -> bytes:
        """Return all buffered bytes concatenated."""
        return b"".join(self._chunks)


class ProcessRegistry:
    """Tracks spawned terminal processes and keeps their PTY fds drained.

    Each registered process gets a background reader that continuously
    reads from the PTY master fd.  This prevents the kernel buffer from
    filling up (which would block the child process).  Output is forwarded
    to an optional subscriber queue (used by the terminal WS handler).

    A ring buffer of recent raw output is kept per process so that
    reconnecting WS clients can replay the last screen's worth of data.

    An ``on_activity`` callback is invoked whenever the process produces
    output, so external code (e.g. SessionManager) can update timestamps.
    """

    def __init__(self) -> None:
        self._processes: dict[str, TerminalProcess] = {}
        self._drain_tasks: dict[str, asyncio.Task] = {}
        self._ring_buffers: dict[str, _RingBuffer] = {}
        # Per-key subscriber queue — set by WS handler, cleared on disconnect.
        self._subscribers: dict[str, asyncio.Queue[bytes | None]] = {}
        # Callback: async def cb(session_id: str) -> None
        self._activity_callback: Callable | None = None

    def set_activity_callback(self, cb: Callable) -> None:
        """Register a callback fired on PTY output activity."""
        self._activity_callback = cb

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, key: str, process: TerminalProcess) -> None:
        """Register a process and start its background drain loop."""
        self._processes[key] = process
        self._ring_buffers[key] = _RingBuffer()
        self._start_drain(key, process)

    def unregister(self, key: str) -> TerminalProcess | None:
        """Unregister and return a process (stops drain)."""
        self._stop_drain(key)
        self._ring_buffers.pop(key, None)
        return self._processes.pop(key, None)

    def get(self, key: str) -> TerminalProcess | None:
        return self._processes.get(key)

    def keys(self) -> list[str]:
        return list(self._processes.keys())

    # ------------------------------------------------------------------
    # Output subscription (for terminal WS handler)
    # ------------------------------------------------------------------

    def subscribe(self, key: str) -> asyncio.Queue[bytes | None]:
        """Subscribe to PTY output for a process.

        Returns a queue that receives live output from the drain loop.
        The ring buffer snapshot is replayed as the first item so the
        client immediately sees recent terminal content.
        """
        q: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=1024)
        # Replay ring buffer so reconnecting clients see recent output
        ring = self._ring_buffers.get(key)
        if ring is not None:
            snapshot = ring.snapshot()
            if snapshot:
                q.put_nowait(snapshot)
        self._subscribers[key] = q
        return q

    def unsubscribe(self, key: str) -> None:
        """Remove the output subscriber for a process."""
        self._subscribers.pop(key, None)

    def notify_input_activity(self, key: str) -> None:
        """Called by the WS handler when user input is written to the PTY."""
        proc = self._processes.get(key)
        if proc is not None:
            proc.had_user_input = True
            self._fire_activity(proc)

    # ------------------------------------------------------------------
    # Persistent drain loop
    # ------------------------------------------------------------------

    def _start_drain(self, key: str, proc: TerminalProcess) -> None:
        """Start a background task that reads from the PTY fd."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.warning("No running event loop — drain not started for %s", key)
            return
        task = loop.create_task(self._drain_loop(key, proc))
        self._drain_tasks[key] = task

    def _stop_drain(self, key: str) -> None:
        task = self._drain_tasks.pop(key, None)
        if task is not None and not task.done():
            task.cancel()
        self._subscribers.pop(key, None)

    async def _drain_loop(self, key: str, proc: TerminalProcess) -> None:
        """Read from PTY fd forever, forwarding to subscriber if present."""
        loop = asyncio.get_running_loop()
        internal_q: asyncio.Queue[bytes | None] = asyncio.Queue()

        def _on_readable() -> None:
            try:
                data = os.read(proc.fd, _READ_CHUNK_SIZE)
                if data:
                    internal_q.put_nowait(data)
                else:
                    internal_q.put_nowait(None)  # EOF
            except OSError:
                internal_q.put_nowait(None)

        try:
            loop.add_reader(proc.fd, _on_readable)
        except Exception:
            logger.debug("Cannot add reader for fd=%d key=%s", proc.fd, key)
            return

        ring = self._ring_buffers.get(key)

        try:
            while True:
                try:
                    data = await asyncio.wait_for(internal_q.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue

                if data is None:
                    break  # Process exited

                # Store in ring buffer
                if ring is not None:
                    ring.append(data)

                # Update activity
                self._fire_activity(proc)

                # Forward to subscriber if any
                sub = self._subscribers.get(key)
                if sub is not None:
                    try:
                        sub.put_nowait(data)
                    except asyncio.QueueFull:
                        # Subscriber is slow — drop oldest and retry
                        try:
                            sub.get_nowait()
                        except asyncio.QueueEmpty:
                            pass
                        try:
                            sub.put_nowait(data)
                        except asyncio.QueueFull:
                            pass
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.debug("Drain loop error for key=%s", key, exc_info=True)
        finally:
            try:
                loop.remove_reader(proc.fd)
            except Exception:
                pass
            # Signal EOF to any subscriber
            sub = self._subscribers.get(key)
            if sub is not None:
                try:
                    sub.put_nowait(None)
                except asyncio.QueueFull:
                    pass

    def _fire_activity(self, proc: TerminalProcess) -> None:
        cb = self._activity_callback
        if cb is not None and proc.session_id:
            try:
                asyncio.ensure_future(cb(proc.session_id))
            except RuntimeError:
                pass

    # ------------------------------------------------------------------
    # Termination
    # ------------------------------------------------------------------

    def terminate(self, key: str) -> None:
        """Terminate a registered process."""
        self._stop_drain(key)
        self._ring_buffers.pop(key, None)
        proc = self._processes.pop(key, None)
        if proc is None:
            return
        try:
            os.close(proc.fd)
        except OSError:
            pass
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            try:
                os.kill(proc.pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass

    def terminate_all(self) -> None:
        """Terminate all registered processes."""
        for key in list(self._processes.keys()):
            self.terminate(key)

    def cleanup_orphaned(self) -> None:
        """Remove entries for processes that are no longer running."""
        dead_keys: list[str] = []
        for key, proc in self._processes.items():
            try:
                os.kill(proc.pid, 0)
            except (ProcessLookupError, PermissionError):
                dead_keys.append(key)

        for key in dead_keys:
            self._stop_drain(key)
            self._ring_buffers.pop(key, None)
            proc = self._processes.pop(key, None)
            if proc:
                try:
                    os.close(proc.fd)
                except OSError:
                    pass
