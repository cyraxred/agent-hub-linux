"""Git worktree service ported from Swift GitWorktreeService.swift."""

from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path

from agent_hub.config.defaults import GIT_COMMAND_TIMEOUT, GIT_WORKTREE_TIMEOUT
from agent_hub.models.worktree import (
    RemoteBranch,
    WorktreeCreationProgressCompleted,
    WorktreeCreationProgressFailed,
    WorktreeCreationProgressPreparing,
    WorktreeCreationProgressUpdatingFiles,
)

logger = logging.getLogger(__name__)

_PROGRESS_RE = re.compile(r"Updating files:\s+\d+%\s+\((\d+)/(\d+)\)")


class WorktreeError(Exception):
    """Worktree operation error."""


async def _run_git(
    args: list[str], cwd: str, timeout: float = GIT_COMMAND_TIMEOUT
) -> tuple[str, str, int]:
    """Run a git command and return (stdout, stderr, returncode)."""
    proc = await asyncio.create_subprocess_exec(
        "git", *args,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError as e:
        proc.kill()
        raise WorktreeError("Git command timed out") from e
    return (
        stdout.decode("utf-8", errors="replace"),
        stderr.decode("utf-8", errors="replace"),
        proc.returncode or 0,
    )


async def find_git_root(path: str) -> str:
    """Find the git repository root for a path."""
    stdout, stderr, rc = await _run_git(["rev-parse", "--show-toplevel"], cwd=path)
    if rc != 0:
        raise WorktreeError(f"Not a git repository: {path} ({stderr.strip()})")
    return stdout.strip()


async def get_current_branch(repo_path: str) -> str:
    """Get the current branch name."""
    stdout, _, rc = await _run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_path)
    if rc != 0:
        return ""
    return stdout.strip()


async def get_current_branch_fast(repo_path: str) -> str:
    """Get the current branch by reading .git/HEAD directly."""
    head_file = Path(repo_path) / ".git" / "HEAD"
    try:
        content = head_file.read_text().strip()
        if content.startswith("ref: refs/heads/"):
            return content[len("ref: refs/heads/"):]
        return content[:8]
    except OSError:
        return await get_current_branch(repo_path)


async def get_remote_branches(repo_path: str) -> list[RemoteBranch]:
    """Get all remote branches."""
    stdout, _, rc = await _run_git(["branch", "-r", "--format=%(refname:short)"], cwd=repo_path)
    if rc != 0:
        return []
    branches: list[RemoteBranch] = []
    for line in stdout.strip().splitlines():
        line = line.strip()
        if not line or "HEAD" in line:
            continue
        parts = line.split("/", 1)
        remote = parts[0] if len(parts) > 1 else "origin"
        branches.append(RemoteBranch(name=line, remote=remote))
    return branches


async def fetch_and_get_remote_branches(repo_path: str) -> list[RemoteBranch]:
    """Fetch from all remotes and return remote branches."""
    await _run_git(["fetch", "--all", "--prune"], cwd=repo_path, timeout=GIT_WORKTREE_TIMEOUT)
    return await get_remote_branches(repo_path)


async def get_local_branches(repo_path: str) -> list[RemoteBranch]:
    """Get all local branches."""
    stdout, _, rc = await _run_git(["branch", "--format=%(refname:short)"], cwd=repo_path)
    if rc != 0:
        return []
    branches: list[RemoteBranch] = []
    for line in stdout.strip().splitlines():
        line = line.strip()
        if line:
            branches.append(RemoteBranch(name=line, remote=""))
    return branches


async def has_uncommitted_changes(repo_path: str) -> bool:
    """Check if the repo has uncommitted changes."""
    stdout, _, _ = await _run_git(["status", "--porcelain"], cwd=repo_path)
    return bool(stdout.strip())


def sanitize_branch_name(branch: str) -> str:
    """Sanitize a string for use as a git branch name."""
    sanitized = re.sub(r"[^a-zA-Z0-9/_.-]", "-", branch)
    sanitized = re.sub(r"-+", "-", sanitized)
    return sanitized.strip("-")


def worktree_directory_name(branch: str, repo_name: str) -> str:
    """Generate a worktree directory name."""
    sanitized = sanitize_branch_name(branch)
    return f"{repo_name}-{sanitized}"


async def create_worktree(
    repo_path: str,
    branch: str,
    directory_name: str,
) -> str:
    """Create a worktree for an existing branch."""
    parent = str(Path(repo_path).parent)
    worktree_path = str(Path(parent) / directory_name)

    if Path(worktree_path).exists():
        raise WorktreeError(f"Directory already exists: {worktree_path}")

    _, stderr, rc = await _run_git(
        ["worktree", "add", worktree_path, branch],
        cwd=repo_path,
        timeout=GIT_WORKTREE_TIMEOUT,
    )
    if rc != 0:
        raise WorktreeError(f"Failed to create worktree: {stderr.strip()}")
    return worktree_path


async def create_worktree_with_new_branch(
    repo_path: str,
    new_branch_name: str,
    directory_name: str,
    start_point: str | None = None,
    on_progress: object | None = None,
) -> str:
    """Create a worktree with a new branch."""
    parent = str(Path(repo_path).parent)
    worktree_path = str(Path(parent) / directory_name)

    if Path(worktree_path).exists():
        raise WorktreeError(f"Directory already exists: {worktree_path}")

    if on_progress is not None:
        await on_progress(WorktreeCreationProgressPreparing(message="Creating worktree..."))  # type: ignore[misc]

    args = ["worktree", "add", "-b", new_branch_name, worktree_path]
    if start_point:
        args.append(start_point)

    proc = await asyncio.create_subprocess_exec(
        "git", *args,
        cwd=repo_path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    try:
        stderr_data = b""
        assert proc.stderr is not None
        while True:
            try:
                chunk = await asyncio.wait_for(proc.stderr.read(4096), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            if not chunk:
                break
            stderr_data += chunk
            text = chunk.decode("utf-8", errors="replace")

            if on_progress is not None:
                match = _PROGRESS_RE.search(text)
                if match:
                    current = int(match.group(1))
                    total = int(match.group(2))
                    await on_progress(  # type: ignore[misc]
                        WorktreeCreationProgressUpdatingFiles(current=current, total=total)
                    )

        await asyncio.wait_for(proc.wait(), timeout=GIT_WORKTREE_TIMEOUT)

    except asyncio.TimeoutError:
        proc.kill()
        if on_progress is not None:
            await on_progress(WorktreeCreationProgressFailed(error="Timed out"))  # type: ignore[misc]
        raise WorktreeError("Worktree creation timed out")

    if proc.returncode != 0:
        err = stderr_data.decode("utf-8", errors="replace").strip()
        if on_progress is not None:
            await on_progress(WorktreeCreationProgressFailed(error=err))  # type: ignore[misc]
        raise WorktreeError(f"Failed to create worktree: {err}")

    if on_progress is not None:
        await on_progress(WorktreeCreationProgressCompleted(path=worktree_path))  # type: ignore[misc]

    return worktree_path


async def remove_worktree(worktree_path: str, force: bool = False) -> None:
    """Remove a worktree."""
    args = ["worktree", "remove"]
    if force:
        args.append("--force")
    args.append(worktree_path)

    _, stderr, rc = await _run_git(args, cwd=worktree_path)
    if rc != 0:
        raise WorktreeError(f"Failed to remove worktree: {stderr.strip()}")


async def capture_stash(repo_path: str) -> str | None:
    """Stash changes and return the stash ref."""
    stdout, _, rc = await _run_git(["stash", "create"], cwd=repo_path)
    ref = stdout.strip()
    if rc != 0 or not ref:
        return None
    await _run_git(["stash", "store", ref, "-m", "AgentHub auto-stash"], cwd=repo_path)
    return ref


async def apply_stash(ref: str, path: str) -> None:
    """Apply a stash ref."""
    _, stderr, rc = await _run_git(["stash", "apply", ref], cwd=path)
    if rc != 0:
        raise WorktreeError(f"Failed to apply stash: {stderr.strip()}")
