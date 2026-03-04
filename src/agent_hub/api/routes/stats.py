"""Stats routes for retrieving and refreshing global statistics."""

from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from agent_hub.models.stats import GlobalStatsCache

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/stats", tags=["stats"])


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class StatsResponse(BaseModel):
    """Response wrapping the global stats cache for a provider."""

    provider: str
    stats: GlobalStatsCache | None = None


class StatsRefreshResponse(BaseModel):
    """Response after a stats refresh."""

    provider: str
    success: bool = True
    message: str = ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_provider(request: Request):
    return request.app.state.provider


def _get_stats_service(provider, provider_name: str):
    """Return the stats service for the given provider.

    The provider exposes ``stats_service`` (Claude) and
    ``codex_stats_service`` (Codex) properties.
    """
    if provider_name == "codex":
        return provider.codex_stats_service
    return provider.stats_service


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/{provider}", response_model=StatsResponse)
async def get_stats(
    provider: Literal["claude", "codex"],
    request: Request,
) -> StatsResponse:
    """Get the cached global statistics for the given provider."""
    prov = _get_provider(request)
    service = _get_stats_service(prov, provider)
    return StatsResponse(provider=provider, stats=service.stats)


@router.post("/{provider}/refresh", response_model=StatsRefreshResponse)
async def refresh_stats(
    provider: Literal["claude", "codex"],
    request: Request,
) -> StatsRefreshResponse:
    """Force-refresh the global statistics for the given provider."""
    prov = _get_provider(request)
    service = _get_stats_service(prov, provider)

    try:
        await service.refresh()
    except Exception as exc:
        logger.exception("Failed to refresh stats for %s", provider)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to refresh stats: {exc}",
        ) from exc

    return StatsRefreshResponse(
        provider=provider,
        success=True,
        message=f"{provider} stats refreshed",
    )
