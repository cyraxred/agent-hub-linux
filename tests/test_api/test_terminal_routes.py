"""Tests for agent_hub.api.routes.terminal module."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_hub.services.process_registry import ProcessRegistry
from agent_hub.services.terminal_launcher import TerminalProcess


def _create_test_app(registry: ProcessRegistry | None = None) -> FastAPI:
    """Create a FastAPI app with terminal routes and a mock registry."""
    from agent_hub.api.routes.terminal import router

    app = FastAPI()
    if registry is None:
        registry = ProcessRegistry()
    app.state.process_registry = registry
    app.state.provider = MagicMock()
    app.state.provider.process_registry = registry
    # Provide settings with additional_cli_paths
    app.state.provider.settings = MagicMock()
    app.state.provider.settings.additional_cli_paths = []
    app.include_router(router)
    return app


class TestListTerminals:
    """Tests for GET /api/terminal."""

    def test_empty_list(self) -> None:
        app = _create_test_app()
        with TestClient(app) as client:
            resp = client.get("/api/terminal")
        assert resp.status_code == 200
        data = resp.json()
        assert data["terminals"] == []
        assert data["total"] == 0

    @patch("agent_hub.services.process_registry.os.kill")
    def test_list_with_terminals(self, mock_kill: MagicMock) -> None:
        mock_kill.return_value = None  # Process is alive
        registry = ProcessRegistry()
        proc = TerminalProcess(pid=123, fd=10, session_id="s1", project_path="/proj")
        registry.register("term-s1", proc)

        app = _create_test_app(registry)
        with TestClient(app) as client:
            resp = client.get("/api/terminal")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["terminals"][0]["key"] == "term-s1"
        assert data["terminals"][0]["pid"] == 123


class TestResizeTerminal:
    """Tests for POST /api/terminal/{key}/resize."""

    def test_resize_not_found(self) -> None:
        app = _create_test_app()
        with TestClient(app) as client:
            resp = client.post(
                "/api/terminal/nonexistent/resize",
                json={"rows": 40, "cols": 120},
            )
        assert resp.status_code == 404

    @patch("agent_hub.api.routes.terminal.resize_terminal")
    def test_resize_success(self, mock_resize: MagicMock) -> None:
        registry = ProcessRegistry()
        proc = TerminalProcess(pid=123, fd=10)
        registry.register("key1", proc)

        app = _create_test_app(registry)
        with TestClient(app) as client:
            resp = client.post(
                "/api/terminal/key1/resize",
                json={"rows": 40, "cols": 120},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        mock_resize.assert_called_once_with(10, 40, 120)


class TestTerminateTerminal:
    """Tests for DELETE /api/terminal/{key}."""

    def test_terminate_not_found(self) -> None:
        app = _create_test_app()
        with TestClient(app) as client:
            resp = client.delete("/api/terminal/nonexistent")
        assert resp.status_code == 404

    @patch("agent_hub.services.process_registry.os.close")
    @patch("agent_hub.services.process_registry.os.killpg")
    @patch("agent_hub.services.process_registry.os.getpgid", return_value=100)
    def test_terminate_success(
        self,
        mock_getpgid: MagicMock,
        mock_killpg: MagicMock,
        mock_close: MagicMock,
    ) -> None:
        registry = ProcessRegistry()
        proc = TerminalProcess(pid=123, fd=10)
        registry.register("key1", proc)

        app = _create_test_app(registry)
        with TestClient(app) as client:
            resp = client.delete("/api/terminal/key1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["terminated"] is True
        assert registry.get("key1") is None


class TestLaunchTerminal:
    """Tests for POST /api/terminal/launch."""

    @patch("agent_hub.api.routes.terminal.find_cli_command", return_value=None)
    def test_launch_command_not_found(self, mock_find: MagicMock) -> None:
        app = _create_test_app()
        with TestClient(app) as client:
            resp = client.post(
                "/api/terminal/launch",
                json={"command": "claude", "project_path": "/proj"},
            )
        assert resp.status_code == 404

    @patch("agent_hub.api.routes.terminal.spawn_terminal")
    @patch("agent_hub.api.routes.terminal.find_cli_command", return_value="/usr/local/bin/claude")
    def test_launch_success(
        self, mock_find: MagicMock, mock_spawn: MagicMock
    ) -> None:
        mock_spawn.return_value = TerminalProcess(pid=999, fd=20)

        app = _create_test_app()
        with TestClient(app) as client:
            resp = client.post(
                "/api/terminal/launch",
                json={
                    "command": "claude",
                    "project_path": "/proj",
                    "session_id": "sess-1",
                },
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["pid"] == 999
        assert data["fd"] == 20
        assert data["session_id"] == "sess-1"
