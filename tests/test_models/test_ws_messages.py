"""Tests for agent_hub.models.ws_messages module."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import TypeAdapter

from agent_hub.models.monitor_state import SessionMonitorState
from agent_hub.models.search import SearchMatchField, SessionSearchResult
from agent_hub.models.session import SelectedRepository
from agent_hub.models.stats import GlobalStatsCache
from agent_hub.models.ws_messages import (
    ClientMessage,
    ClientMessageRefreshSessions,
    ClientMessageSubscribeSession,
    ClientMessageTerminalInput,
    ClientMessageTerminalResize,
    ClientMessageUnsubscribeSession,
    ServerMessage,
    ServerMessageError,
    ServerMessageSearchResults,
    ServerMessageSessionsUpdated,
    ServerMessageSessionStateUpdate,
    ServerMessageStatsUpdated,
    ServerMessageTerminalOutput,
)


# ---------- ServerMessage ----------


class TestServerMessages:
    """Tests for all ServerMessage discriminated union variants."""

    def test_session_state_update(self) -> None:
        state = SessionMonitorState()
        msg = ServerMessageSessionStateUpdate(
            session_id="sess-001",
            state=state,
        )
        assert msg.kind == "session_state_update"
        assert msg.session_id == "sess-001"

    def test_sessions_updated(self) -> None:
        msg = ServerMessageSessionsUpdated(repositories=[])
        assert msg.kind == "sessions_updated"
        assert msg.repositories == []

    def test_stats_updated(self) -> None:
        stats = GlobalStatsCache()
        msg = ServerMessageStatsUpdated(provider="claude", stats=stats)
        assert msg.kind == "stats_updated"
        assert msg.provider == "claude"

    def test_search_results(self) -> None:
        msg = ServerMessageSearchResults(results=[])
        assert msg.kind == "search_results"
        assert msg.results == []

    def test_terminal_output(self) -> None:
        msg = ServerMessageTerminalOutput(session_key="key-1", data="hello\n")
        assert msg.kind == "terminal_output"
        assert msg.session_key == "key-1"
        assert msg.data == "hello\n"

    def test_error(self) -> None:
        msg = ServerMessageError(message="Something went wrong")
        assert msg.kind == "error"
        assert msg.message == "Something went wrong"

    def test_server_message_discriminated_union(self) -> None:
        adapter = TypeAdapter(ServerMessage)
        variants = [
            {
                "kind": "session_state_update",
                "session_id": "s1",
                "state": SessionMonitorState().model_dump(),
            },
            {"kind": "sessions_updated", "repositories": []},
            {
                "kind": "stats_updated",
                "provider": "claude",
                "stats": GlobalStatsCache().model_dump(),
            },
            {"kind": "search_results", "results": []},
            {"kind": "terminal_output", "session_key": "k1", "data": "x"},
            {"kind": "error", "message": "err"},
        ]
        for v in variants:
            parsed = adapter.validate_python(v)
            assert parsed.kind == v["kind"]

    def test_server_message_serialization_roundtrip(self) -> None:
        adapter = TypeAdapter(ServerMessage)
        msg = ServerMessageError(message="test")
        data = adapter.dump_python(msg)
        restored = adapter.validate_python(data)
        assert restored.kind == "error"
        assert restored.message == "test"  # type: ignore[union-attr]


# ---------- ClientMessage ----------


class TestClientMessages:
    """Tests for all ClientMessage discriminated union variants."""

    def test_subscribe_session(self) -> None:
        msg = ClientMessageSubscribeSession(
            session_id="sess-001",
            project_path="/proj",
            session_file_path="/home/.claude/projects/x/sess-001.jsonl",
        )
        assert msg.kind == "subscribe_session"
        assert msg.session_id == "sess-001"
        assert msg.project_path == "/proj"
        assert msg.session_file_path == "/home/.claude/projects/x/sess-001.jsonl"

    def test_unsubscribe_session(self) -> None:
        msg = ClientMessageUnsubscribeSession(session_id="sess-001")
        assert msg.kind == "unsubscribe_session"

    def test_terminal_input(self) -> None:
        msg = ClientMessageTerminalInput(session_key="key-1", data="ls\n")
        assert msg.kind == "terminal_input"
        assert msg.session_key == "key-1"
        assert msg.data == "ls\n"

    def test_terminal_resize(self) -> None:
        msg = ClientMessageTerminalResize(
            session_key="key-1", cols=120, rows=40
        )
        assert msg.kind == "terminal_resize"
        assert msg.cols == 120
        assert msg.rows == 40

    def test_refresh_sessions(self) -> None:
        msg = ClientMessageRefreshSessions()
        assert msg.kind == "refresh_sessions"

    def test_client_message_discriminated_union(self) -> None:
        adapter = TypeAdapter(ClientMessage)
        variants = [
            {
                "kind": "subscribe_session",
                "session_id": "s1",
                "project_path": "/p",
                "session_file_path": "/f.jsonl",
            },
            {"kind": "unsubscribe_session", "session_id": "s1"},
            {"kind": "terminal_input", "session_key": "k", "data": "x"},
            {"kind": "terminal_resize", "session_key": "k", "cols": 80, "rows": 24},
            {"kind": "refresh_sessions"},
        ]
        for v in variants:
            parsed = adapter.validate_python(v)
            assert parsed.kind == v["kind"]

    def test_client_message_serialization_roundtrip(self) -> None:
        adapter = TypeAdapter(ClientMessage)
        msg = ClientMessageTerminalInput(session_key="k", data="test")
        data = adapter.dump_python(msg)
        restored = adapter.validate_python(data)
        assert restored.kind == "terminal_input"
