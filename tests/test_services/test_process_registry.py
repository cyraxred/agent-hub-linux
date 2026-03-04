"""Tests for agent_hub.services.process_registry module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agent_hub.services.process_registry import ProcessRegistry
from agent_hub.services.terminal_launcher import TerminalProcess


# ---------- ProcessRegistry ----------


class TestProcessRegistry:
    """Tests for the ProcessRegistry class."""

    @pytest.fixture()
    def registry(self) -> ProcessRegistry:
        return ProcessRegistry()

    @pytest.fixture()
    def mock_process(self) -> TerminalProcess:
        return TerminalProcess(pid=12345, fd=10)

    def test_register_and_get(
        self, registry: ProcessRegistry, mock_process: TerminalProcess
    ) -> None:
        registry.register("key1", mock_process)
        result = registry.get("key1")
        assert result is not None
        assert result.pid == 12345

    def test_get_nonexistent(self, registry: ProcessRegistry) -> None:
        assert registry.get("nonexistent") is None

    def test_unregister(
        self, registry: ProcessRegistry, mock_process: TerminalProcess
    ) -> None:
        registry.register("key1", mock_process)
        removed = registry.unregister("key1")
        assert removed is not None
        assert removed.pid == 12345
        assert registry.get("key1") is None

    def test_unregister_nonexistent(self, registry: ProcessRegistry) -> None:
        result = registry.unregister("nonexistent")
        assert result is None

    def test_keys(self, registry: ProcessRegistry) -> None:
        registry.register("a", TerminalProcess(pid=1, fd=1))
        registry.register("b", TerminalProcess(pid=2, fd=2))
        keys = registry.keys()
        assert set(keys) == {"a", "b"}

    def test_keys_empty(self, registry: ProcessRegistry) -> None:
        assert registry.keys() == []

    @patch("agent_hub.services.process_registry.os.close")
    @patch("agent_hub.services.process_registry.os.killpg")
    @patch("agent_hub.services.process_registry.os.getpgid", return_value=12345)
    def test_terminate(
        self,
        mock_getpgid: MagicMock,
        mock_killpg: MagicMock,
        mock_close: MagicMock,
        registry: ProcessRegistry,
        mock_process: TerminalProcess,
    ) -> None:
        registry.register("key1", mock_process)
        registry.terminate("key1")

        mock_close.assert_called_once_with(10)
        mock_killpg.assert_called_once()
        assert registry.get("key1") is None

    def test_terminate_nonexistent(self, registry: ProcessRegistry) -> None:
        # Should not raise
        registry.terminate("nonexistent")

    @patch("agent_hub.services.process_registry.os.close")
    @patch("agent_hub.services.process_registry.os.killpg", side_effect=ProcessLookupError)
    @patch("agent_hub.services.process_registry.os.kill", side_effect=ProcessLookupError)
    @patch("agent_hub.services.process_registry.os.getpgid", return_value=12345)
    def test_terminate_already_dead(
        self,
        mock_getpgid: MagicMock,
        mock_kill: MagicMock,
        mock_killpg: MagicMock,
        mock_close: MagicMock,
        registry: ProcessRegistry,
        mock_process: TerminalProcess,
    ) -> None:
        registry.register("key1", mock_process)
        # Should not raise even if process is already dead
        registry.terminate("key1")
        assert registry.get("key1") is None

    @patch("agent_hub.services.process_registry.os.close")
    @patch("agent_hub.services.process_registry.os.killpg")
    @patch("agent_hub.services.process_registry.os.getpgid", return_value=100)
    def test_terminate_all(
        self,
        mock_getpgid: MagicMock,
        mock_killpg: MagicMock,
        mock_close: MagicMock,
        registry: ProcessRegistry,
    ) -> None:
        registry.register("a", TerminalProcess(pid=1, fd=1))
        registry.register("b", TerminalProcess(pid=2, fd=2))
        registry.terminate_all()
        assert registry.keys() == []

    @patch("agent_hub.services.process_registry.os.close")
    @patch("agent_hub.services.process_registry.os.kill")
    def test_cleanup_orphaned_removes_dead(
        self,
        mock_kill: MagicMock,
        mock_close: MagicMock,
        registry: ProcessRegistry,
    ) -> None:
        registry.register("alive", TerminalProcess(pid=1, fd=1))
        registry.register("dead", TerminalProcess(pid=2, fd=2))

        # First call (for pid 1) succeeds (alive), second (for pid 2) raises (dead)
        mock_kill.side_effect = [None, ProcessLookupError]

        registry.cleanup_orphaned()

        assert registry.get("alive") is not None
        assert registry.get("dead") is None

    @patch("agent_hub.services.process_registry.os.kill")
    def test_cleanup_orphaned_all_alive(
        self,
        mock_kill: MagicMock,
        registry: ProcessRegistry,
    ) -> None:
        registry.register("a", TerminalProcess(pid=1, fd=1))
        registry.register("b", TerminalProcess(pid=2, fd=2))
        mock_kill.return_value = None  # All alive

        registry.cleanup_orphaned()

        assert len(registry.keys()) == 2
