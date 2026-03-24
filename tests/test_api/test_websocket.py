"""Tests for WebSocket handler and ConnectionManager."""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, PropertyMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_hub.models.monitor_state import SessionMonitorState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_mock_provider() -> MagicMock:
    """Create a mock AgentHubProvider for WebSocket tests."""
    provider = MagicMock()

    # Claude transcript registry
    claude_registry = MagicMock()
    claude_registry.get_transcript = MagicMock(return_value=None)
    claude_registry.register_transcript = AsyncMock()
    claude_registry.set_monitored = MagicMock()
    provider.claude_transcript_registry = claude_registry

    # Codex transcript registry
    codex_registry = MagicMock()
    codex_registry.get_transcript = MagicMock(return_value=None)
    codex_registry.register_transcript = AsyncMock()
    codex_registry.set_monitored = MagicMock()
    provider.codex_transcript_registry = codex_registry

    # Process registry
    process_registry = MagicMock()
    provider.process_registry = process_registry

    # Session manager
    session_manager = MagicMock()
    session_manager._schedule_notify = MagicMock()
    session_manager.set_manual_monitoring = AsyncMock()
    session_manager.get_all_sessions = MagicMock(return_value=[])
    provider.session_manager = session_manager

    return provider


def _create_ws_test_app(provider: MagicMock) -> FastAPI:
    """Create a minimal FastAPI app with WebSocket endpoint and mock provider."""

    @asynccontextmanager
    async def test_lifespan(app: FastAPI) -> AsyncGenerator[None]:
        app.state.provider = provider
        app.state.settings = MagicMock()
        app.state.process_registry = provider.process_registry
        yield

    app = FastAPI(lifespan=test_lifespan)

    # Register the WebSocket endpoint
    from agent_hub.api.websocket.handler import websocket_endpoint

    app.websocket("/ws")(websocket_endpoint)

    return app


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestWebSocketConnection:
    """Test WebSocket connection lifecycle."""

    def test_websocket_connect_and_disconnect(self) -> None:
        """Test that a WebSocket can connect and disconnect cleanly."""
        provider = _build_mock_provider()
        app = _create_ws_test_app(provider)

        with TestClient(app) as client:
            with client.websocket_connect("/ws") as ws:
                # Connection established; simply close it
                pass  # WebSocket disconnects on context exit

    def test_websocket_subscribe_session(self) -> None:
        """Test sending a subscribe_session message starts monitoring."""
        provider = _build_mock_provider()
        app = _create_ws_test_app(provider)

        with TestClient(app) as client:
            with client.websocket_connect("/ws") as ws:
                msg = {
                    "kind": "subscribe_session",
                    "session_id": "test-session-001",
                    "project_path": "/home/user/project",
                    "session_file_path": "/home/user/.claude/projects/x/test-session-001.jsonl",
                }
                ws.send_text(json.dumps(msg))

        provider.claude_transcript_registry.register_transcript.assert_called_once()

    def test_websocket_unsubscribe_session(self) -> None:
        """Test sending an unsubscribe_session message."""
        provider = _build_mock_provider()
        app = _create_ws_test_app(provider)

        with TestClient(app) as client:
            with client.websocket_connect("/ws") as ws:
                # First subscribe
                subscribe_msg = {
                    "kind": "subscribe_session",
                    "session_id": "test-session-001",
                    "project_path": "/home/user/project",
                    "session_file_path": "/home/user/.claude/projects/x/test-session-001.jsonl",
                }
                ws.send_text(json.dumps(subscribe_msg))

                # Then unsubscribe
                unsub_msg = {
                    "kind": "unsubscribe_session",
                    "session_id": "test-session-001",
                }
                ws.send_text(json.dumps(unsub_msg))
                # Unsubscribe does not send a response, so no receive needed

    def test_websocket_invalid_message(self) -> None:
        """Test that an invalid message returns an error."""
        provider = _build_mock_provider()
        app = _create_ws_test_app(provider)

        with TestClient(app) as client:
            with client.websocket_connect("/ws") as ws:
                ws.send_text("not valid json at all {{{")
                response = ws.receive_json()
                assert response["kind"] == "error"
                assert "Invalid message" in response["message"]

    def test_websocket_unknown_kind(self) -> None:
        """Test that an unknown message kind returns an error."""
        provider = _build_mock_provider()
        app = _create_ws_test_app(provider)

        with TestClient(app) as client:
            with client.websocket_connect("/ws") as ws:
                msg = {"kind": "totally_unknown_kind"}
                ws.send_text(json.dumps(msg))
                response = ws.receive_json()
                assert response["kind"] == "error"

    def test_websocket_refresh_sessions(self) -> None:
        """Test sending a refresh_sessions message triggers session broadcasts."""
        provider = _build_mock_provider()
        app = _create_ws_test_app(provider)

        with TestClient(app) as client:
            with client.websocket_connect("/ws") as ws:
                msg = {"kind": "refresh_sessions"}
                ws.send_text(json.dumps(msg))
                # Refresh now triggers _schedule_notify per session (no
                # sessions in mock → no broadcast), so we just verify no error.

    def test_websocket_subscribe_starts_monitoring(self) -> None:
        """Verify that subscribing actually calls start_monitoring on the watcher."""
        provider = _build_mock_provider()
        app = _create_ws_test_app(provider)

        with TestClient(app) as client:
            with client.websocket_connect("/ws") as ws:
                msg = {
                    "kind": "subscribe_session",
                    "session_id": "sess-abc",
                    "project_path": "/proj",
                    "session_file_path": "/home/user/.claude/projects/x/sess-abc.jsonl",
                }
                ws.send_text(json.dumps(msg))

        provider.claude_transcript_registry.register_transcript.assert_called_once_with(
            session_id="sess-abc",
            project_path="/proj",
            file_path="/home/user/.claude/projects/x/sess-abc.jsonl",
        )
