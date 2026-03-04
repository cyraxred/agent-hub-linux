"""Search routes for querying and reindexing sessions."""

from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from agent_hub.models.search import SessionSearchResult

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/search", tags=["search"])


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class SearchResponse(BaseModel):
    """Response containing search results."""

    query: str
    results: list[SessionSearchResult]
    total: int


class ReindexResponse(BaseModel):
    """Response after rebuilding the search index."""

    success: bool = True
    indexed_count: int = 0
    message: str = ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_provider(request: Request):
    return request.app.state.provider


def _get_search_service(provider, provider_name: str):
    """Return the search service for the given provider.

    The provider is expected to expose ``claude_search`` and ``codex_search``
    attributes for the respective search services.
    """
    if provider_name == "codex":
        return provider.codex_search
    return provider.claude_search


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("", response_model=SearchResponse)
async def search_sessions(
    request: Request,
    q: str = Query(default="", description="Search query string"),
    filter_path: str | None = Query(default=None, description="Filter results to this repository path"),
    provider: Literal["claude", "codex"] = Query(default="claude", description="Which provider to search"),
) -> SearchResponse:
    """Search sessions using the in-memory search index.

    Supports fuzzy matching against session slugs, project paths, branches,
    first messages, and summaries.
    """
    prov = _get_provider(request)
    service = _get_search_service(prov, provider)

    if not q.strip():
        return SearchResponse(query=q, results=[], total=0)

    try:
        results = await service.search(query=q, filter_path=filter_path)
    except Exception as exc:
        logger.exception("Search failed for query=%r", q)
        raise HTTPException(
            status_code=500,
            detail=f"Search failed: {exc}",
        ) from exc

    return SearchResponse(query=q, results=results, total=len(results))


@router.post("/reindex", response_model=ReindexResponse)
async def reindex(
    request: Request,
    provider: Literal["claude", "codex"] | None = Query(
        default=None,
        description="Provider to reindex, or both if omitted",
    ),
) -> ReindexResponse:
    """Rebuild the search index from scratch.

    If ``provider`` is specified only that provider is reindexed, otherwise
    both Claude and Codex indices are rebuilt.
    """
    prov = _get_provider(request)
    total_indexed = 0

    try:
        if provider is None or provider == "claude":
            claude_search = _get_search_service(prov, "claude")
            await claude_search.rebuild_index()
            total_indexed += await claude_search.indexed_session_count()

        if provider is None or provider == "codex":
            codex_search = _get_search_service(prov, "codex")
            await codex_search.rebuild_index()
            total_indexed += await codex_search.indexed_session_count()

    except Exception as exc:
        logger.exception("Reindex failed")
        raise HTTPException(
            status_code=500,
            detail=f"Reindex failed: {exc}",
        ) from exc

    return ReindexResponse(
        success=True,
        indexed_count=total_indexed,
        message=f"Indexed {total_indexed} sessions",
    )
