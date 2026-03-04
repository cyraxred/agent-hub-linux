"""Git diff service ported from Swift GitDiffService.swift."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from uuid import uuid4

from agent_hub.config.defaults import GIT_DIFF_TIMEOUT
from agent_hub.models.git_diff import DiffMode, GitDiffFileEntry, GitDiffState

logger = logging.getLogger(__name__)


class GitDiffError(Exception):
    """Git diff operation error."""


async def _run_git(
    args: list[str],
    cwd: str,
    timeout: float = GIT_DIFF_TIMEOUT,
) -> tuple[str, str]:
    """Run a git command and return (stdout, stderr)."""
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
        raise GitDiffError("Git command timed out") from e

    return stdout.decode("utf-8", errors="replace"), stderr.decode("utf-8", errors="replace")


def _parse_numstat(output: str, repo_path: str) -> list[GitDiffFileEntry]:
    """Parse git diff --numstat output into file entries."""
    entries: list[GitDiffFileEntry] = []
    for line in output.strip().splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        adds_str, dels_str, file_path = parts[0], parts[1], parts[2]
        try:
            additions = int(adds_str) if adds_str != "-" else 0
            deletions = int(dels_str) if dels_str != "-" else 0
        except ValueError:
            additions = 0
            deletions = 0

        abs_path = str(Path(repo_path) / file_path)
        entries.append(
            GitDiffFileEntry(
                id=uuid4(),
                file_path=abs_path,
                relative_path=file_path,
                additions=additions,
                deletions=deletions,
            )
        )
    return entries


async def find_git_root(path: str) -> str:
    """Find the git repository root for a path."""
    stdout, _ = await _run_git(["rev-parse", "--show-toplevel"], cwd=path)
    result = stdout.strip()
    if not result:
        raise GitDiffError(f"Not a git repository: {path}")
    return result


async def detect_base_branch(repo_path: str) -> str:
    """Detect the base branch (main/master) for a repository."""
    for branch in ("main", "master"):
        stdout, _ = await _run_git(
            ["rev-parse", "--verify", f"refs/heads/{branch}"],
            cwd=repo_path,
        )
        if stdout.strip():
            return branch
    return "main"


async def get_unstaged_changes(repo_path: str) -> GitDiffState:
    """Get unstaged (working directory) changes."""
    stdout, _ = await _run_git(["diff", "--numstat"], cwd=repo_path)
    entries = _parse_numstat(stdout, repo_path)
    return GitDiffState(files=entries)


async def get_staged_changes(repo_path: str) -> GitDiffState:
    """Get staged (index) changes."""
    stdout, _ = await _run_git(["diff", "--staged", "--numstat"], cwd=repo_path)
    entries = _parse_numstat(stdout, repo_path)
    return GitDiffState(files=entries)


async def get_branch_changes(repo_path: str, base_branch: str) -> GitDiffState:
    """Get changes between current branch and base branch (three-dot diff)."""
    stdout, _ = await _run_git(
        ["diff", f"{base_branch}...HEAD", "--numstat"], cwd=repo_path
    )
    entries = _parse_numstat(stdout, repo_path)
    return GitDiffState(files=entries)


async def get_changes(
    repo_path: str, mode: DiffMode, base_branch: str | None = None
) -> GitDiffState:
    """Get changes based on diff mode."""
    if mode == DiffMode.unstaged:
        return await get_unstaged_changes(repo_path)
    elif mode == DiffMode.staged:
        return await get_staged_changes(repo_path)
    elif mode == DiffMode.branch:
        branch = base_branch or await detect_base_branch(repo_path)
        return await get_branch_changes(repo_path, branch)
    return GitDiffState(files=[])


async def get_untracked_changes(repo_path: str) -> list[GitDiffFileEntry]:
    """Get untracked files."""
    stdout, _ = await _run_git(
        ["ls-files", "--others", "--exclude-standard", "-z"], cwd=repo_path
    )
    entries: list[GitDiffFileEntry] = []
    for file_path in stdout.split("\0"):
        file_path = file_path.strip()
        if not file_path:
            continue
        abs_path = str(Path(repo_path) / file_path)
        entries.append(
            GitDiffFileEntry(
                id=uuid4(),
                file_path=abs_path,
                relative_path=file_path,
                additions=0,
                deletions=0,
            )
        )
    return entries


async def get_unified_diff_output(
    repo_path: str, mode: DiffMode, base_branch: str | None = None
) -> str:
    """Get unified diff output as a string."""
    if mode == DiffMode.unstaged:
        stdout, _ = await _run_git(["diff"], cwd=repo_path)
    elif mode == DiffMode.staged:
        stdout, _ = await _run_git(["diff", "--staged"], cwd=repo_path)
    elif mode == DiffMode.branch:
        branch = base_branch or await detect_base_branch(repo_path)
        stdout, _ = await _run_git(["diff", f"{branch}...HEAD"], cwd=repo_path)
    else:
        stdout = ""
    return stdout


async def get_unified_file_diff(
    file_path: str,
    repo_path: str,
    mode: DiffMode = DiffMode.unstaged,
    base_branch: str | None = None,
) -> str:
    """Get unified diff for a specific file."""
    rel = str(Path(file_path).relative_to(repo_path)) if file_path.startswith(repo_path) else file_path
    if mode == DiffMode.unstaged:
        stdout, _ = await _run_git(["diff", "--", rel], cwd=repo_path)
    elif mode == DiffMode.staged:
        stdout, _ = await _run_git(["diff", "--staged", "--", rel], cwd=repo_path)
    elif mode == DiffMode.branch:
        branch = base_branch or await detect_base_branch(repo_path)
        stdout, _ = await _run_git(["diff", f"{branch}...HEAD", "--", rel], cwd=repo_path)
    else:
        stdout = ""
    return stdout


async def get_file_diff(
    file_path: str,
    repo_path: str,
    mode: DiffMode = DiffMode.unstaged,
    base_branch: str | None = None,
) -> tuple[str, str]:
    """Get old and new content for a specific file diff."""
    rel = str(Path(file_path).relative_to(repo_path)) if file_path.startswith(repo_path) else file_path

    # Get old content
    if mode == DiffMode.staged:
        old_stdout, _ = await _run_git(["show", f"HEAD:{rel}"], cwd=repo_path)
    elif mode == DiffMode.branch:
        branch = base_branch or await detect_base_branch(repo_path)
        old_stdout, _ = await _run_git(["show", f"{branch}:{rel}"], cwd=repo_path)
    else:
        old_stdout, _ = await _run_git(["show", f"HEAD:{rel}"], cwd=repo_path)

    # Get new content
    if mode == DiffMode.staged:
        new_stdout, _ = await _run_git(["show", f":{rel}"], cwd=repo_path)
    else:
        try:
            abs_path = Path(repo_path) / rel
            new_stdout = abs_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            new_stdout = ""

    return old_stdout, new_stdout
