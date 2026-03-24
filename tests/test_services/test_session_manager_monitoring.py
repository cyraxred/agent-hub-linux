"""Unit tests for SessionManager monitoring flags."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent_hub.models.monitor_state import SessionMonitorState
from agent_hub.models.process_info import ClaudeProcessCategory, ClaudeProcessInfo
from agent_hub.services.session_manager import Session, SessionManager


@pytest.fixture()
def sm() -> SessionManager:
    manager = SessionManager()
    # Stub out debounced notify to avoid creating tasks
    manager._schedule_notify = MagicMock()
    return manager


@pytest.fixture()
def mock_tracker() -> MagicMock:
    tracker = MagicMock()
    tracker.get_all_process_states.return_value = {}
    tracker.get_pending_attention_for_session.return_value = []
    return tracker


@pytest.fixture()
def mock_registry() -> MagicMock:
    registry = MagicMock()
    registry.set_monitored = MagicMock()
    return registry


class TestManualMonitoring:
    async def test_set_manual_monitoring_true(
        self, sm: SessionManager, mock_registry: MagicMock
    ):
        sm._sessions["s1"] = Session(session_id="s1", provider="claude")
        sm._claude_registry = mock_registry

        await sm.set_manual_monitoring("s1", True)

        assert sm._sessions["s1"].manual_monitoring is True
        mock_registry.set_monitored.assert_called_with("s1", True)

    async def test_set_manual_monitoring_false(
        self, sm: SessionManager, mock_registry: MagicMock
    ):
        sm._sessions["s1"] = Session(session_id="s1", provider="claude")
        sm._sessions["s1"].manual_monitoring = True
        sm._claude_registry = mock_registry

        await sm.set_manual_monitoring("s1", False)

        assert sm._sessions["s1"].manual_monitoring is False
        # should_monitor is False (no auto either), so set_monitored(False)
        mock_registry.set_monitored.assert_called_with("s1", False)


class TestAutoMonitoring:
    async def test_auto_monitoring_from_terminal_connected(
        self, sm: SessionManager, mock_registry: MagicMock, mock_tracker: MagicMock
    ):
        process = ClaudeProcessInfo(
            pid=1234,
            session_id="s1",
            category=ClaudeProcessCategory.hub,
            terminal_connected=True,
        )
        sm._sessions["s1"] = Session(session_id="s1", provider="claude", process=process)
        sm._claude_registry = mock_registry
        sm._tracker = mock_tracker

        sm._recompute_auto_monitoring(sm._sessions["s1"])

        assert sm._sessions["s1"].auto_monitoring is True
        mock_registry.set_monitored.assert_called_with("s1", True)

    async def test_auto_monitoring_from_attention(
        self, sm: SessionManager, mock_registry: MagicMock, mock_tracker: MagicMock
    ):
        process = ClaudeProcessInfo(
            pid=1234,
            session_id="s1",
            category=ClaudeProcessCategory.hub,
            terminal_connected=False,
        )
        sm._sessions["s1"] = Session(session_id="s1", provider="claude", process=process)
        sm._claude_registry = mock_registry
        sm._tracker = mock_tracker
        # Simulate pending attention
        mock_tracker.get_pending_attention_for_session.return_value = [MagicMock()]

        sm._recompute_auto_monitoring(sm._sessions["s1"])

        assert sm._sessions["s1"].auto_monitoring is True

    async def test_auto_monitoring_cleared_on_process_death(
        self, sm: SessionManager, mock_registry: MagicMock, mock_tracker: MagicMock
    ):
        sm._sessions["s1"] = Session(
            session_id="s1", provider="claude", auto_monitoring=True
        )
        sm._claude_registry = mock_registry
        sm._tracker = mock_tracker

        # No process → auto_monitoring should be False
        sm._recompute_auto_monitoring(sm._sessions["s1"])

        assert sm._sessions["s1"].auto_monitoring is False
        mock_registry.set_monitored.assert_called_with("s1", False)

    async def test_auto_monitoring_cleared_on_attention_resolved(
        self, sm: SessionManager, mock_registry: MagicMock, mock_tracker: MagicMock
    ):
        process = ClaudeProcessInfo(
            pid=1234,
            session_id="s1",
            category=ClaudeProcessCategory.hub,
            terminal_connected=False,
        )
        sm._sessions["s1"] = Session(
            session_id="s1", provider="claude", process=process, auto_monitoring=True
        )
        sm._claude_registry = mock_registry
        sm._tracker = mock_tracker
        # No pending attention
        mock_tracker.get_pending_attention_for_session.return_value = []

        sm._recompute_auto_monitoring(sm._sessions["s1"])

        assert sm._sessions["s1"].auto_monitoring is False

    async def test_manual_and_auto_both_true(
        self, sm: SessionManager, mock_registry: MagicMock, mock_tracker: MagicMock
    ):
        """When manual cleared but auto still True, should_monitor stays True."""
        process = ClaudeProcessInfo(
            pid=1234,
            session_id="s1",
            category=ClaudeProcessCategory.hub,
            terminal_connected=True,
        )
        sm._sessions["s1"] = Session(
            session_id="s1",
            provider="claude",
            process=process,
            manual_monitoring=True,
            auto_monitoring=True,
        )
        sm._claude_registry = mock_registry
        sm._tracker = mock_tracker

        # Clear manual
        await sm.set_manual_monitoring("s1", False)

        # auto is still True → should_monitor stays True
        assert sm._sessions["s1"].should_monitor is True
        mock_registry.set_monitored.assert_called_with("s1", True)


class TestTranscriptHandlers:
    async def test_handle_transcript_added_creates_session(self, sm: SessionManager):
        transcript = MagicMock()
        transcript.file_path = "/home/user/.claude/projects/test/session.jsonl"
        transcript.project_path = "/home/user/project"
        transcript.provider = "claude"

        await sm.handle_transcript_added("s1", transcript)

        session = sm.get_session("s1")
        assert session is not None
        assert session.session_file_path == transcript.file_path
        assert session.project_path == "/home/user/project"

    async def test_handle_transcript_removed_without_process(self, sm: SessionManager):
        sm._sessions["s1"] = Session(session_id="s1")

        await sm.handle_transcript_removed("s1")

        assert sm.get_session("s1") is None

    async def test_handle_transcript_removed_with_process(self, sm: SessionManager):
        process = ClaudeProcessInfo(
            pid=1234,
            session_id="s1",
            category=ClaudeProcessCategory.hub,
        )
        sm._sessions["s1"] = Session(
            session_id="s1", process=process, manual_monitoring=True
        )

        await sm.handle_transcript_removed("s1")

        # Session should still exist but monitoring cleared
        session = sm.get_session("s1")
        assert session is not None
        assert session.manual_monitoring is False
        assert session.auto_monitoring is False
        assert session.monitor_state is None

    async def test_handle_transcript_added_merges_with_existing(self, sm: SessionManager):
        """Transcript added for a session that already has a process — metadata merged, process kept."""
        process = ClaudeProcessInfo(
            pid=1234,
            session_id="s1",
            category=ClaudeProcessCategory.hub,
        )
        sm._sessions["s1"] = Session(
            session_id="s1", process=process, provider="claude"
        )

        transcript = MagicMock()
        transcript.session_id = "s1"
        transcript.project_path = "/home/user/project"
        transcript.file_path = "/path/to/session.jsonl"
        transcript.first_message = "Hello"
        transcript.slug = "my-session"

        await sm.handle_transcript_added("s1", transcript)

        session = sm.get_session("s1")
        assert session is not None
        # Process should not be overwritten
        assert session.process is process
        # Metadata from transcript should be merged
        assert session.slug == "my-session"
        assert session.first_message == "Hello"
