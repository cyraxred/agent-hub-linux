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
from agent_hub.models.session import CLISession, SelectedRepository, WorktreeBranch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_mock_provider() -> MagicMock:
    """Create a mock AgentHubProvider for WebSocket tests."""
    provider = MagicMock()

    # Claude monitor
    claude_monitor = MagicMock()
    type(claude_monitor).repositories = PropertyMock(return_value=[])
    claude_monitor.refresh_sessions = AsyncMock()
    provider.claude_monitor = claude_monitor

    # Codex monitor
    codex_monitor = MagicMock()
    type(codex_monitor).repositories = PropertyMock(return_value=[])
    codex_monitor.refresh_sessions = AsyncMock()
    provider.codex_monitor = codex_monitor

    # Claude watcher
    claude_watcher = MagicMock()
    claude_watcher.start_monitoring = AsyncMock()
    claude_watcher.stop_monitoring = AsyncMock()
    claude_watcher.get_state = AsyncMock(return_value=SessionMonitorState())
    provider.claude_watcher = claude_watcher

    # Codex watcher
    codex_watcher = MagicMock()
    codex_watcher.start_monitoring = AsyncMock()
    codex_watcher.stop_monitoring = AsyncMock()
    codex_watcher.get_state = AsyncMock(return_value=None)
    provider.codex_watcher = codex_watcher

    # Process registry
    process_registry = MagicMock()
    provider.process_registry = process_registry

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
        """Test sending a subscribe_session message."""
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

                # The handler should call start_monitoring and then
                # broadcast the current state back to us.
                response = ws.receive_json()
                assert response["kind"] == "session_state_update"
                assert response["session_id"] == "test-session-001"
                assert "state" in response

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
                # Consume the state update
                ws.receive_json()

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
        """Test sending a refresh_sessions message."""
        provider = _build_mock_provider()
        app = _create_ws_test_app(provider)

        with TestClient(app) as client:
            with client.websocket_connect("/ws") as ws:
                msg = {"kind": "refresh_sessions"}
                ws.send_text(json.dumps(msg))

                # After refresh, the handler broadcasts sessions_updated
                response = ws.receive_json()
                assert response["kind"] == "sessions_updated"
                assert "repositories" in response

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
                ws.receive_json()

        provider.claude_watcher.start_monitoring.assert_called_once_with(
            session_id="sess-abc",
            project_path="/proj",
            session_file_path="/home/user/.claude/projects/x/sess-abc.jsonl",
        )
