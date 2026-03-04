"""Tests for session API routes."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, PropertyMock

import pytest
from fastapi.testclient import TestClient

from agent_hub.models.monitor_state import SessionMonitorState
from agent_hub.models.session import CLISession, SelectedRepository, WorktreeBranch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session(
    session_id: str = "sess-001",
    project_path: str = "/home/user/project",
    is_active: bool = True,
) -> CLISession:
    return CLISession(
        id=session_id,
        project_path=project_path,
        last_activity_at=datetime(2025, 6, 15, 10, 0, tzinfo=timezone.utc),
        is_active=is_active,
        first_message="Hello",
    )


def _make_repo(sessions: list[CLISession] | None = None) -> SelectedRepository:
    if sessions is None:
        sessions = [_make_session()]
    return SelectedRepository(
        path="/home/user/project",
        name="project",
        worktrees=[
            WorktreeBranch(
                name="main",
                path="/home/user/project",
                sessions=sessions,
                is_expanded=True,
            ),
        ],
        is_expanded=True,
    )


def _build_mock_provider(
    claude_repos: list[SelectedRepository] | None = None,
    codex_repos: list[SelectedRepository] | None = None,
) -> MagicMock:
    """Create a mock AgentHubProvider with configurable repositories."""
    provider = MagicMock()

    # Claude monitor
    claude_monitor = MagicMock()
    type(claude_monitor).repositories = PropertyMock(
        return_value=claude_repos if claude_repos is not None else [_make_repo()]
    )
    claude_monitor.refresh_sessions = AsyncMock()
    claude_monitor.add_repository = AsyncMock(return_value=_make_repo())
    claude_monitor.remove_repository = AsyncMock()
    provider.claude_monitor = claude_monitor

    # Codex monitor
    codex_monitor = MagicMock()
    type(codex_monitor).repositories = PropertyMock(
        return_value=codex_repos if codex_repos is not None else []
    )
    codex_monitor.refresh_sessions = AsyncMock()
    provider.codex_monitor = codex_monitor

    # Claude watcher
    claude_watcher = MagicMock()
    claude_watcher.start_monitoring = AsyncMock()
    claude_watcher.stop_monitoring = AsyncMock()
    claude_watcher.get_state = AsyncMock(return_value=SessionMonitorState())
    claude_watcher.refresh_state = AsyncMock()
    provider.claude_watcher = claude_watcher

    # Codex watcher
    codex_watcher = MagicMock()
    codex_watcher.start_monitoring = AsyncMock()
    codex_watcher.stop_monitoring = AsyncMock()
    codex_watcher.get_state = AsyncMock(return_value=None)
    provider.codex_watcher = codex_watcher

    # Process registry
    provider.process_registry = MagicMock()

    return provider


def _create_test_app(provider: MagicMock) -> Any:
    """Create a FastAPI app with pre-set state (no lifespan needed)."""
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse

    app = FastAPI()

    # Set state directly -- bypasses lifespan
    app.state.provider = provider
    app.state.settings = MagicMock()
    app.state.process_registry = provider.process_registry

    @app.get("/api/health")
    async def health() -> JSONResponse:
        return JSONResponse({"status": "ok"})

    # Register the session and repository routers
    from agent_hub.api.routes.sessions import router as sessions_router
    from agent_hub.api.routes.repositories import router as repositories_router

    app.include_router(sessions_router)
    app.include_router(repositories_router)

    return app


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestHealthEndpoint:
    """Test the /api/health endpoint."""

    def test_health_returns_200(self) -> None:
        provider = _build_mock_provider()
        app = _create_test_app(provider)
        with TestClient(app) as client:
            resp = client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


class TestSessionsRoutes:
    """Tests for /api/sessions endpoints."""

    def test_list_sessions_returns_list(self) -> None:
        provider = _build_mock_provider()
        app = _create_test_app(provider)
        with TestClient(app) as client:
            resp = client.get("/api/sessions")
        assert resp.status_code == 200
        data = resp.json()
        assert "sessions" in data
        assert "total" in data
        assert isinstance(data["sessions"], list)
        assert data["total"] >= 1

    def test_list_sessions_empty(self) -> None:
        provider = _build_mock_provider(claude_repos=[], codex_repos=[])
        app = _create_test_app(provider)
        with TestClient(app) as client:
            resp = client.get("/api/sessions")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["sessions"] == []

    def test_get_session_found(self) -> None:
        session = _make_session(session_id="test-id-123")
        repo = _make_repo(sessions=[session])
        provider = _build_mock_provider(claude_repos=[repo])
        app = _create_test_app(provider)
        with TestClient(app) as client:
            resp = client.get("/api/sessions/test-id-123")
        assert resp.status_code == 200
        data = resp.json()
        assert data["session"]["id"] == "test-id-123"
        assert data["provider"] == "claude"

    def test_get_session_not_found(self) -> None:
        provider = _build_mock_provider(claude_repos=[], codex_repos=[])
        app = _create_test_app(provider)
        with TestClient(app) as client:
            resp = client.get("/api/sessions/nonexistent")
        assert resp.status_code == 404

    def test_get_session_monitor_state(self) -> None:
        provider = _build_mock_provider()
        app = _create_test_app(provider)
        with TestClient(app) as client:
            resp = client.get("/api/sessions/sess-001/state")
        assert resp.status_code == 200
        data = resp.json()
        assert data["session_id"] == "sess-001"
        assert data["monitoring"] is True

    def test_start_monitoring(self) -> None:
        provider = _build_mock_provider()
        app = _create_test_app(provider)
        with TestClient(app) as client:
            resp = client.post(
                "/api/sessions/sess-001/monitor",
                json={
                    "project_path": "/home/user/project",
                    "session_file_path": "/home/.claude/sessions/sess-001.jsonl",
                    "provider": "claude",
                },
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["session_id"] == "sess-001"
        assert data["monitoring"] is True
        provider.claude_watcher.start_monitoring.assert_called_once()

    def test_stop_monitoring(self) -> None:
        provider = _build_mock_provider()
        app = _create_test_app(provider)
        with TestClient(app) as client:
            resp = client.delete("/api/sessions/sess-001/monitor")
        assert resp.status_code == 200
        data = resp.json()
        assert data["monitoring"] is False
        provider.claude_watcher.stop_monitoring.assert_called_once()

    def test_refresh_session_state(self) -> None:
        provider = _build_mock_provider()
        app = _create_test_app(provider)
        with TestClient(app) as client:
            resp = client.post("/api/sessions/sess-001/refresh")
        assert resp.status_code == 200
        data = resp.json()
        assert data["session_id"] == "sess-001"
        provider.claude_watcher.refresh_state.assert_called_once()


class TestRepositoriesRoutes:
    """Tests for /api/repositories endpoints."""

    def test_list_repositories(self) -> None:
        provider = _build_mock_provider()
        app = _create_test_app(provider)
        with TestClient(app) as client:
            resp = client.get("/api/repositories")
        assert resp.status_code == 200
        data = resp.json()
        assert "repositories" in data
        assert "total" in data
        assert isinstance(data["repositories"], list)
        assert data["total"] >= 1

    def test_list_repositories_empty(self) -> None:
        provider = _build_mock_provider(claude_repos=[])
        app = _create_test_app(provider)
        with TestClient(app) as client:
            resp = client.get("/api/repositories")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0

    def test_add_repository(self) -> None:
        provider = _build_mock_provider()
        app = _create_test_app(provider)
        with TestClient(app) as client:
            resp = client.post(
                "/api/repositories",
                json={"path": "/home/user/new-project", "provider": "claude"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["already_exists"] is False
        assert data["repository"] is not None

    def test_add_repository_already_exists(self) -> None:
        provider = _build_mock_provider()
        provider.claude_monitor.add_repository = AsyncMock(return_value=None)
        app = _create_test_app(provider)
        with TestClient(app) as client:
            resp = client.post(
                "/api/repositories",
                json={"path": "/home/user/existing-project", "provider": "claude"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["already_exists"] is True

    def test_refresh_all_sessions(self) -> None:
        provider = _build_mock_provider()
        app = _create_test_app(provider)
        with TestClient(app) as client:
            resp = client.post("/api/repositories/refresh")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
