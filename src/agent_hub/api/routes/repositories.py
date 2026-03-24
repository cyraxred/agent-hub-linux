"""Repository routes for adding, removing, and refreshing monitored repositories.

NOTE: Worktree detection was previously handled by CLISessionMonitorService.
It ran ``git worktree list`` and grouped sessions by branch — purely a UI
grouping concern.  This has been removed.  If needed in the future, add a
``/api/repositories/{path}/worktrees`` endpoint that calls ``git worktree list``
and returns the result, letting the frontend handle grouping.
"""

from __future__ import annotations

import logging
from pathlib import PurePosixPath
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from agent_hub.models.session import CLISession, SelectedRepository, WorktreeBranch

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/repositories", tags=["repositories"])


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class RepositoryListResponse(BaseModel):
    """Response with the list of watched repositories and their sessions."""

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


def _build_repositories(provider) -> list[SelectedRepository]:
    """Build SelectedRepository objects with sessions grouped inside."""
    sm = provider.session_manager
    repos_paths = sm.get_repositories()
    all_sessions = sm.get_all_cli_sessions()

    # Group sessions by project_path
    sessions_by_repo: dict[str, list[CLISession]] = {rp: [] for rp in repos_paths}
    for s in all_sessions:
        if s.project_path in sessions_by_repo:
            sessions_by_repo[s.project_path].append(s)

    result: list[SelectedRepository] = []
    for repo_path in sorted(repos_paths):
        sessions = sessions_by_repo.get(repo_path, [])
        # Sort sessions by most recent first
        sessions.sort(key=lambda s: s.last_activity_at, reverse=True)

        # Single default worktree containing all sessions
        wt = WorktreeBranch(
            name=PurePosixPath(repo_path).name,
            path=repo_path,
            is_worktree=False,
            sessions=sessions,
        )

        result.append(SelectedRepository(
            path=repo_path,
            name=PurePosixPath(repo_path).name,
            worktrees=[wt],
        ))

    return result


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("", response_model=RepositoryListResponse)
async def list_repositories(
    request: Request,
    provider: Literal["claude", "codex"] = "claude",
) -> RepositoryListResponse:
    """List all watched repositories with their sessions."""
    prov = _get_provider(request)
    repos = _build_repositories(prov)
    return RepositoryListResponse(repositories=repos, total=len(repos))


@router.post("", response_model=AddRepositoryResponse)
async def add_repository(
    body: AddRepositoryRequest,
    request: Request,
) -> AddRepositoryResponse:
    """Add a repository to watch for the given provider."""
    prov = _get_provider(request)

    try:
        added = await prov.session_manager.add_repository(body.path, body.provider)
    except Exception as exc:
        logger.exception("Failed to add repository %s", body.path)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to add repository: {exc}",
        ) from exc

    if not added:
        return AddRepositoryResponse(repository=None, already_exists=True)

    from pathlib import Path
    resolved = str(Path(body.path).resolve())

    # Build the repository object for the response
    repos = _build_repositories(prov)
    repo = next((r for r in repos if r.path == resolved), None)

    return AddRepositoryResponse(
        repository=repo,
        already_exists=False,
    )


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

    try:
        await prov.session_manager.remove_repository(resolved_path, provider)
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
    """Refresh response (no-op — sessions are discovered automatically by TranscriptRegistry)."""
    return RefreshResponse(success=True, message="Sessions refreshed")
