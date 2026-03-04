"""Repository routes for adding, removing, and refreshing monitored repositories."""

from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from agent_hub.models.session import SelectedRepository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/repositories", tags=["repositories"])


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class RepositoryListResponse(BaseModel):
    """Response with the full list of repositories."""

    repositories: list[SelectedRepository]
    total: int


class AddRepositoryRequest(BaseModel):
    """Body for adding a new repository to monitor."""

    path: str
    provider: Literal["claude", "codex"] = "claude"


class AddRepositoryResponse(BaseModel):
    """Response after adding a repository."""

    repository: SelectedRepository | None = None
    already_exists: bool = False


class RemoveRepositoryResponse(BaseModel):
    """Response after removing a repository."""

    removed: bool = True
    path: str


class RefreshResponse(BaseModel):
    """Response after refreshing sessions."""

    success: bool = True
    message: str = ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_provider(request: Request):
    return request.app.state.provider


def _get_monitor(provider, provider_name: str):
    """Return the correct session monitor for the given provider name."""
    if provider_name == "codex":
        return provider.codex_monitor
    return provider.claude_monitor


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("", response_model=RepositoryListResponse)
async def list_repositories(
    request: Request,
    provider: Literal["claude", "codex"] = "claude",
) -> RepositoryListResponse:
    """List all monitored repositories for the given provider."""
    prov = _get_provider(request)
    monitor = _get_monitor(prov, provider)
    repos = monitor.repositories
    return RepositoryListResponse(repositories=repos, total=len(repos))


@router.post("", response_model=AddRepositoryResponse)
async def add_repository(
    body: AddRepositoryRequest,
    request: Request,
) -> AddRepositoryResponse:
    """Add a repository to the monitor for the given provider."""
    prov = _get_provider(request)
    monitor = _get_monitor(prov, body.provider)

    try:
        repo = await monitor.add_repository(body.path)
    except Exception as exc:
        logger.exception("Failed to add repository %s", body.path)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to add repository: {exc}",
        ) from exc

    if repo is None:
        return AddRepositoryResponse(repository=None, already_exists=True)

    return AddRepositoryResponse(repository=repo, already_exists=False)


@router.delete("/{path:path}", response_model=RemoveRepositoryResponse)
async def remove_repository(
    path: str,
    request: Request,
    provider: Literal["claude", "codex"] = "claude",
) -> RemoveRepositoryResponse:
    """Remove a repository from monitoring.

    The path is passed as a URL path parameter (may contain slashes).
    The leading slash from the absolute path is preserved by the
    ``{path:path}`` capture.
    """
    # FastAPI's ``{path:path}`` strips the leading ``/``, so we restore it
    # when the path looks like an absolute filesystem path.
    resolved_path = path if path.startswith("/") else f"/{path}"

    prov = _get_provider(request)
    monitor = _get_monitor(prov, provider)

    try:
        await monitor.remove_repository(resolved_path)
    except Exception as exc:
        logger.exception("Failed to remove repository %s", resolved_path)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to remove repository: {exc}",
        ) from exc

    return RemoveRepositoryResponse(removed=True, path=resolved_path)


@router.post("/refresh", response_model=RefreshResponse)
async def refresh_all_sessions(
    request: Request,
    provider: Literal["claude", "codex"] | None = None,
) -> RefreshResponse:
    """Refresh sessions across all repositories.

    If ``provider`` is specified, only that provider is refreshed.
    Otherwise both providers are refreshed.
    """
    prov = _get_provider(request)

    try:
        if provider is None or provider == "claude":
            await prov.claude_monitor.refresh_sessions()
        if provider is None or provider == "codex":
            await prov.codex_monitor.refresh_sessions()
    except Exception as exc:
        logger.exception("Failed to refresh sessions")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to refresh sessions: {exc}",
        ) from exc

    return RefreshResponse(success=True, message="Sessions refreshed")
