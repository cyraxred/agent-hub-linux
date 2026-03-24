"""Tests for session API routes."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, PropertyMock

import pytest
from fastapi.testclient import TestClient

from agent_hub.models.monitor_state import SessionMonitorState
from agent_hub.models.session import CLISession


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session(
    session_id: str = "sess-001",
    project_path: str = "/home/user/project",
) -> CLISession:
    return CLISession(
        id=session_id,
        project_path=project_path,
        last_activity_at=datetime(2025, 6, 15, 10, 0, tzinfo=timezone.utc),
        first_message="Hello",
    )


def _build_mock_provider(
    sessions: list[CLISession] | None = None,
) -> MagicMock:
    """Create a mock AgentHubProvider with configurable sessions."""
    provider = MagicMock()

    if sessions is None:
        sessions = [_make_session()]

    # Claude transcript registry
    mock_transcript = MagicMock()
    mock_transcript.state = SessionMonitorState()
    mock_transcript.is_monitored = True
    mock_transcript.refresh = AsyncMock()

    claude_registry = MagicMock()
    claude_registry.get_transcript = MagicMock(return_value=mock_transcript)
    claude_registry.register_transcript = AsyncMock(return_value=mock_transcript)
    claude_registry.set_monitored = MagicMock()
    provider.claude_transcript_registry = claude_registry

    # Codex transcript registry
    codex_registry = MagicMock()
    codex_registry.get_transcript = MagicMock(return_value=None)
    codex_registry.register_transcript = AsyncMock()
    codex_registry.set_monitored = MagicMock()
    provider.codex_transcript_registry = codex_registry

    # Session manager
    session_manager = MagicMock()
    session_manager.set_manual_monitoring = AsyncMock()
    session_manager.get_all_sessions = MagicMock(return_value=[])
    session_manager.get_all_cli_sessions = MagicMock(return_value=list(sessions))
    session_manager.get_repositories = MagicMock(return_value=["/home/user/project"])
    session_manager.add_repository = AsyncMock(return_value=True)
    session_manager.remove_repository = AsyncMock()

    # find_cli_session: return first matching session
    def _find(sid: str):
        for s in sessions:
            if s.id == sid:
                return s, "claude"
        return None, ""
    session_manager.find_cli_session = MagicMock(side_effect=_find)

    provider.session_manager = session_manager

    # Process tracker / registry
    provider.process_tracker = MagicMock()
    provider.process_tracker.get_unmatched_processes = MagicMock(return_value=[])
    provider.process_registry = MagicMock()

    # Parse cache
    provider.parse_cache = MagicMock()
    provider.parse_cache.get = MagicMock(return_value=None)

    # Settings
    provider.settings = MagicMock()
    provider.settings.claude_data_path = "~/.claude"

    # Metadata store
    provider.metadata_store = MagicMock()
    provider.metadata_store.get_all_custom_names = AsyncMock(return_value={})
    provider.metadata_store.upsert_metadata = AsyncMock()
    provider.metadata_store.delete_metadata = AsyncMock()

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
        provider = _build_mock_provider(sessions=[])
        app = _create_test_app(provider)
        with TestClient(app) as client:
            resp = client.get("/api/sessions")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["sessions"] == []

    def test_get_session_found(self) -> None:
        session = _make_session(session_id="test-id-123")
        provider = _build_mock_provider(sessions=[session])
        app = _create_test_app(provider)
        with TestClient(app) as client:
            resp = client.get("/api/sessions/test-id-123")
        assert resp.status_code == 200
        data = resp.json()
        assert data["session"]["id"] == "test-id-123"
        assert data["provider"] == "claude"

    def test_get_session_not_found(self) -> None:
        provider = _build_mock_provider(sessions=[])
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
        provider.session_manager.set_manual_monitoring.assert_called_once()

    def test_stop_monitoring(self) -> None:
        provider = _build_mock_provider()
        app = _create_test_app(provider)
        with TestClient(app) as client:
            resp = client.delete("/api/sessions/sess-001/monitor")
        assert resp.status_code == 200
        data = resp.json()
        assert data["monitoring"] is False
        provider.session_manager.set_manual_monitoring.assert_called()

    def test_refresh_session_state(self) -> None:
        provider = _build_mock_provider()
        app = _create_test_app(provider)
        with TestClient(app) as client:
            resp = client.post("/api/sessions/sess-001/refresh")
        assert resp.status_code == 200
        data = resp.json()
        assert data["session_id"] == "sess-001"
        provider.claude_transcript_registry.get_transcript.assert_called()


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
        assert data["total"] >= 1
        repo = data["repositories"][0]
        assert repo["path"] == "/home/user/project"
        assert repo["name"] == "project"
        assert "worktrees" in repo
        assert len(repo["worktrees"]) == 1
        # Sessions should be nested inside the worktree
        wt = repo["worktrees"][0]
        assert len(wt["sessions"]) >= 1
        assert wt["sessions"][0]["id"] == "sess-001"

    def test_list_repositories_empty(self) -> None:
        provider = _build_mock_provider()
        provider.session_manager.get_repositories = MagicMock(return_value=[])
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

    def test_add_repository_already_exists(self) -> None:
        provider = _build_mock_provider()
        provider.session_manager.add_repository = AsyncMock(return_value=False)
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
