"""Tests for agent_hub.api.routes.stats module."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_hub.models.stats import GlobalStatsCache


def _create_test_app(
    claude_stats: GlobalStatsCache | None = None,
    codex_stats: GlobalStatsCache | None = None,
) -> FastAPI:
    """Create a FastAPI app with stats routes and a mock provider."""
    from agent_hub.api.routes.stats import router

    app = FastAPI()

    provider = MagicMock()

    # Claude stats service
    claude_service = MagicMock()
    claude_service.stats = claude_stats
    claude_service.refresh = AsyncMock()
    provider.stats_service = claude_service

    # Codex stats service
    codex_service = MagicMock()
    codex_service.stats = codex_stats
    codex_service.refresh = AsyncMock()
    provider.codex_stats_service = codex_service

    app.state.provider = provider
    app.include_router(router)
    return app


class TestGetStats:
    """Tests for GET /api/stats/{provider}."""

    def test_get_claude_stats(self) -> None:
        stats = GlobalStatsCache(total_sessions=10, total_messages=100)
        app = _create_test_app(claude_stats=stats)
        with TestClient(app) as client:
            resp = client.get("/api/stats/claude")
        assert resp.status_code == 200
        data = resp.json()
        assert data["provider"] == "claude"
        assert data["stats"]["total_sessions"] == 10

    def test_get_codex_stats(self) -> None:
        stats = GlobalStatsCache(total_sessions=5, total_messages=50)
        app = _create_test_app(codex_stats=stats)
        with TestClient(app) as client:
            resp = client.get("/api/stats/codex")
        assert resp.status_code == 200
        data = resp.json()
        assert data["provider"] == "codex"
        assert data["stats"]["total_sessions"] == 5

    def test_get_stats_none(self) -> None:
        app = _create_test_app()
        with TestClient(app) as client:
            resp = client.get("/api/stats/claude")
        assert resp.status_code == 200
        data = resp.json()
        assert data["stats"] is None


class TestRefreshStats:
    """Tests for POST /api/stats/{provider}/refresh."""

    def test_refresh_claude_stats(self) -> None:
        app = _create_test_app()
        with TestClient(app) as client:
            resp = client.post("/api/stats/claude/refresh")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["provider"] == "claude"
        assert "refreshed" in data["message"]

    def test_refresh_codex_stats(self) -> None:
        app = _create_test_app()
        with TestClient(app) as client:
            resp = client.post("/api/stats/codex/refresh")
        assert resp.status_code == 200
        data = resp.json()
        assert data["provider"] == "codex"

    def test_refresh_stats_error(self) -> None:
        from agent_hub.api.routes.stats import router

        app = FastAPI()
        provider = MagicMock()
        service = MagicMock()
        service.refresh = AsyncMock(side_effect=RuntimeError("DB error"))
        provider.stats_service = service
        app.state.provider = provider
        app.include_router(router)

        with TestClient(app) as client:
            resp = client.post("/api/stats/claude/refresh")
        assert resp.status_code == 500
