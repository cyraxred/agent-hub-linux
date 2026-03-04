"""Process registry — PID tracking and cleanup."""

from __future__ import annotations

import logging
import os
import signal

from agent_hub.services.terminal_launcher import TerminalProcess

logger = logging.getLogger(__name__)


class ProcessRegistry:
    """Tracks spawned terminal processes for cleanup on exit."""

    def __init__(self) -> None:
        self._processes: dict[str, TerminalProcess] = {}

    def register(self, key: str, process: TerminalProcess) -> None:
        """Register a process under a key."""
        self._processes[key] = process

    def unregister(self, key: str) -> TerminalProcess | None:
        """Unregister and return a process."""
        return self._processes.pop(key, None)

    def get(self, key: str) -> TerminalProcess | None:
        return self._processes.get(key)

    def keys(self) -> list[str]:
        return list(self._processes.keys())

    def terminate(self, key: str) -> None:
        """Terminate a registered process."""
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
            proc = self._processes.pop(key, None)
            if proc:
                try:
                    os.close(proc.fd)
                except OSError:
                    pass
