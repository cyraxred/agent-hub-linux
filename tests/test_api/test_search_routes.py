"""Tests for agent_hub.api.routes.search module."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_hub.models.search import SearchMatchField, SessionSearchResult


def _create_test_app(
    search_results: list[SessionSearchResult] | None = None,
    indexed_count: int = 0,
) -> FastAPI:
    """Create a FastAPI app with search routes and a mock provider."""
    from agent_hub.api.routes.search import router

    app = FastAPI()

    provider = MagicMock()

    # Claude search service
    claude_search = MagicMock()
    claude_search.search = AsyncMock(
        return_value=search_results if search_results is not None else []
    )
    claude_search.rebuild_index = AsyncMock()
    claude_search.indexed_session_count = AsyncMock(return_value=indexed_count)
    provider.claude_search = claude_search

    # Codex search service
    codex_search = MagicMock()
    codex_search.search = AsyncMock(return_value=[])
    codex_search.rebuild_index = AsyncMock()
    codex_search.indexed_session_count = AsyncMock(return_value=0)
    provider.codex_search = codex_search

    app.state.provider = provider
    app.include_router(router)
    return app


class TestSearchSessions:
    """Tests for GET /api/search."""

    def test_search_with_query(self) -> None:
        now = datetime.now(tz=timezone.utc)
        results = [
            SessionSearchResult(
                id="s1",
                slug="fix-bug",
                project_path="/proj",
                last_activity_at=now,
                matched_field=SearchMatchField.slug,
                matched_text="fix-bug",
                relevance_score=95.0,
            ),
        ]
        app = _create_test_app(search_results=results)
        with TestClient(app) as client:
            resp = client.get("/api/search", params={"q": "fix"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["query"] == "fix"
        assert data["total"] == 1
        assert data["results"][0]["id"] == "s1"

    def test_search_empty_query(self) -> None:
        app = _create_test_app()
        with TestClient(app) as client:
            resp = client.get("/api/search", params={"q": ""})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["results"] == []

    def test_search_whitespace_query(self) -> None:
        app = _create_test_app()
        with TestClient(app) as client:
            resp = client.get("/api/search", params={"q": "   "})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0

    def test_search_with_provider(self) -> None:
        app = _create_test_app()
        with TestClient(app) as client:
            resp = client.get(
                "/api/search",
                params={"q": "test", "provider": "codex"},
            )
        assert resp.status_code == 200

    def test_search_with_filter_path(self) -> None:
        app = _create_test_app()
        with TestClient(app) as client:
            resp = client.get(
                "/api/search",
                params={"q": "test", "filter_path": "/proj"},
            )
        assert resp.status_code == 200

    def test_search_error(self) -> None:
        from agent_hub.api.routes.search import router

        app = FastAPI()
        provider = MagicMock()
        service = MagicMock()
        service.search = AsyncMock(side_effect=RuntimeError("index corrupt"))
        provider.claude_search = service
        app.state.provider = provider
        app.include_router(router)

        with TestClient(app) as client:
            resp = client.get("/api/search", params={"q": "test"})
        assert resp.status_code == 500


class TestReindex:
    """Tests for POST /api/search/reindex."""

    def test_reindex_all(self) -> None:
        app = _create_test_app(indexed_count=42)
        with TestClient(app) as client:
            resp = client.post("/api/search/reindex")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["indexed_count"] == 42  # claude only since codex returns 0

    def test_reindex_claude_only(self) -> None:
        app = _create_test_app(indexed_count=10)
        with TestClient(app) as client:
            resp = client.post(
                "/api/search/reindex",
                params={"provider": "claude"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["indexed_count"] == 10

    def test_reindex_error(self) -> None:
        from agent_hub.api.routes.search import router

        app = FastAPI()
        provider = MagicMock()
        service = MagicMock()
        service.rebuild_index = AsyncMock(side_effect=RuntimeError("fail"))
        provider.claude_search = service
        app.state.provider = provider
        app.include_router(router)

        with TestClient(app) as client:
            resp = client.post("/api/search/reindex")
        assert resp.status_code == 500
