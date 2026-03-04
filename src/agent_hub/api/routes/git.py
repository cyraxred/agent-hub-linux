"""Git routes for diffs, branches, worktrees, and repository discovery."""

from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from agent_hub.models.git_diff import DiffMode, GitDiffState, ParsedFileDiff
from agent_hub.models.worktree import RemoteBranch

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/git", tags=["git"])


# ---------------------------------------------------------------------------
# Response / request schemas
# ---------------------------------------------------------------------------


class DiffResponse(BaseModel):
    """Response wrapping a ``GitDiffState`` (file list with stats)."""

    repo_path: str
    mode: DiffMode
    base_branch: str | None = None
    diff: GitDiffState


class UnifiedDiffResponse(BaseModel):
    """Response containing raw unified diff text."""

    repo_path: str
    mode: DiffMode
    base_branch: str | None = None
    diff_text: str


class FileDiffResponse(BaseModel):
    """Response containing old/new content for a single file."""

    file_path: str
    old_content: str
    new_content: str


class BranchListResponse(BaseModel):
    """Response listing branches."""

    branches: list[RemoteBranch]
    total: int


class WorktreeCreateRequest(BaseModel):
    """Request body for creating a git worktree."""

    repo_path: str
    branch: str
    new_branch: bool = False
    start_point: str | None = None


class WorktreeCreateResponse(BaseModel):
    """Response after creating a worktree."""

    worktree_path: str
    branch: str
    success: bool = True


class WorktreeRemoveRequest(BaseModel):
    """Request body for removing a git worktree."""

    worktree_path: str
    force: bool = False


class WorktreeRemoveResponse(BaseModel):
    """Response after removing a worktree."""

    success: bool = True
    message: str = ""


class GitRootResponse(BaseModel):
    """Response returning the git root for a given path."""

    path: str
    git_root: str


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/diff", response_model=DiffResponse)
async def get_diff(
    repo_path: str = Query(..., description="Absolute path to the git repository"),
    mode: DiffMode = Query(default=DiffMode.unstaged, description="Diff mode"),
    base_branch: str | None = Query(default=None, description="Base branch for branch diffs"),
    file_path: str | None = Query(default=None, description="Limit diff to a specific file"),
) -> DiffResponse:
    """Get diff file entries (numstat) for a repository."""
    from agent_hub.services.git_diff_service import GitDiffError, get_changes

    try:
        diff_state = await get_changes(repo_path, mode, base_branch)
    except GitDiffError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Diff failed for %s", repo_path)
        raise HTTPException(status_code=500, detail=f"Diff failed: {exc}") from exc

    # If a file_path filter is given, narrow the results
    if file_path:
        filtered = [f for f in diff_state.files if f.file_path == file_path or f.relative_path == file_path]
        diff_state = GitDiffState(files=filtered)

    return DiffResponse(
        repo_path=repo_path,
        mode=mode,
        base_branch=base_branch,
        diff=diff_state,
    )


@router.get("/diff/unified", response_model=UnifiedDiffResponse)
async def get_unified_diff(
    repo_path: str = Query(..., description="Absolute path to the git repository"),
    mode: DiffMode = Query(default=DiffMode.unstaged, description="Diff mode"),
    base_branch: str | None = Query(default=None, description="Base branch for branch diffs"),
) -> UnifiedDiffResponse:
    """Get the raw unified diff text for a repository."""
    from agent_hub.services.git_diff_service import GitDiffError, get_unified_diff_output

    try:
        diff_text = await get_unified_diff_output(repo_path, mode, base_branch)
    except GitDiffError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Unified diff failed for %s", repo_path)
        raise HTTPException(status_code=500, detail=f"Unified diff failed: {exc}") from exc

    return UnifiedDiffResponse(
        repo_path=repo_path,
        mode=mode,
        base_branch=base_branch,
        diff_text=diff_text,
    )


@router.get("/diff/file", response_model=FileDiffResponse)
async def get_file_diff(
    file_path: str = Query(..., description="Absolute path to the file"),
    repo_path: str = Query(..., description="Absolute path to the git repository"),
    mode: DiffMode = Query(default=DiffMode.unstaged, description="Diff mode"),
    base_branch: str | None = Query(default=None, description="Base branch for branch diffs"),
) -> FileDiffResponse:
    """Get old and new content for a single file diff."""
    from agent_hub.services.git_diff_service import GitDiffError
    from agent_hub.services.git_diff_service import get_file_diff as _get_file_diff

    try:
        old_content, new_content = await _get_file_diff(
            file_path, repo_path, mode, base_branch
        )
    except GitDiffError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("File diff failed for %s", file_path)
        raise HTTPException(status_code=500, detail=f"File diff failed: {exc}") from exc

    return FileDiffResponse(
        file_path=file_path,
        old_content=old_content,
        new_content=new_content,
    )


@router.get("/branches/remote", response_model=BranchListResponse)
async def list_remote_branches(
    repo_path: str = Query(..., description="Absolute path to the git repository"),
    fetch: bool = Query(default=False, description="Fetch from remotes before listing"),
) -> BranchListResponse:
    """List remote branches, optionally fetching first."""
    from agent_hub.services.git_worktree_service import (
        WorktreeError,
        fetch_and_get_remote_branches,
        get_remote_branches,
    )

    try:
        if fetch:
            branches = await fetch_and_get_remote_branches(repo_path)
        else:
            branches = await get_remote_branches(repo_path)
    except WorktreeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Failed to list remote branches for %s", repo_path)
        raise HTTPException(status_code=500, detail=f"Failed to list remote branches: {exc}") from exc

    return BranchListResponse(branches=branches, total=len(branches))


@router.get("/branches/local", response_model=BranchListResponse)
async def list_local_branches(
    repo_path: str = Query(..., description="Absolute path to the git repository"),
) -> BranchListResponse:
    """List local branches in a repository."""
    from agent_hub.services.git_worktree_service import (
        WorktreeError,
        get_local_branches,
    )

    try:
        branches = await get_local_branches(repo_path)
    except WorktreeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Failed to list local branches for %s", repo_path)
        raise HTTPException(status_code=500, detail=f"Failed to list local branches: {exc}") from exc

    return BranchListResponse(branches=branches, total=len(branches))


@router.post("/worktree", response_model=WorktreeCreateResponse)
async def create_worktree(body: WorktreeCreateRequest) -> WorktreeCreateResponse:
    """Create a git worktree.

    If ``new_branch`` is ``True``, a new branch is created at ``start_point``
    (or HEAD). Otherwise an existing branch is checked out into the worktree.
    """
    from agent_hub.services.git_worktree_service import (
        WorktreeError,
        create_worktree as _create_worktree,
        create_worktree_with_new_branch,
        worktree_directory_name,
    )

    dir_name = worktree_directory_name(
        body.branch,
        __import__("pathlib").Path(body.repo_path).name,
    )

    try:
        if body.new_branch:
            wt_path = await create_worktree_with_new_branch(
                repo_path=body.repo_path,
                new_branch_name=body.branch,
                directory_name=dir_name,
                start_point=body.start_point,
            )
        else:
            wt_path = await _create_worktree(
                repo_path=body.repo_path,
                branch=body.branch,
                directory_name=dir_name,
            )
    except WorktreeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Failed to create worktree")
        raise HTTPException(status_code=500, detail=f"Failed to create worktree: {exc}") from exc

    return WorktreeCreateResponse(
        worktree_path=wt_path,
        branch=body.branch,
        success=True,
    )


@router.delete("/worktree", response_model=WorktreeRemoveResponse)
async def remove_worktree(body: WorktreeRemoveRequest) -> WorktreeRemoveResponse:
    """Remove a git worktree."""
    from agent_hub.services.git_worktree_service import (
        WorktreeError,
        remove_worktree as _remove_worktree,
    )

    try:
        await _remove_worktree(body.worktree_path, force=body.force)
    except WorktreeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Failed to remove worktree")
        raise HTTPException(status_code=500, detail=f"Failed to remove worktree: {exc}") from exc

    return WorktreeRemoveResponse(success=True, message="Worktree removed")


@router.get("/root", response_model=GitRootResponse)
async def get_git_root(
    path: str = Query(..., description="Filesystem path to query"),
) -> GitRootResponse:
    """Find the git repository root for a given path."""
    from agent_hub.services.git_diff_service import GitDiffError
    from agent_hub.services.git_diff_service import find_git_root as _find_git_root

    try:
        git_root = await _find_git_root(path)
    except GitDiffError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Failed to find git root for %s", path)
        raise HTTPException(status_code=500, detail=f"Failed to find git root: {exc}") from exc

    return GitRootResponse(path=path, git_root=git_root)
