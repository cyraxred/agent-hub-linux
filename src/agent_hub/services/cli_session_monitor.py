"""Claude session discovery service ported from CLISessionMonitorService.swift."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from agent_hub.models.session import (
    CLISession,
    HistoryEntry,
    SelectedRepository,
    WorktreeBranch,
)
from agent_hub.services.metadata_store import MetadataStore
from agent_hub.services.path_utils import (
    detect_needs_attention,
    encode_project_path,
    find_session_files,
    get_claude_projects_dir,
    get_history_file,
    session_id_from_path,
)
from agent_hub.services.session_jsonl_parser import parse_session_head

logger = logging.getLogger(__name__)

# Activity threshold: if file mtime < 60 seconds ago, session is active
_ACTIVE_THRESHOLD_SECONDS = 60.0


class CLISessionMonitorService:
    """Discovers and manages Claude CLI sessions across repositories."""

    def __init__(
        self,
        claude_data_path: str = "~/.claude",
        metadata_store: MetadataStore | None = None,
    ) -> None:
        self._claude_path = str(Path(claude_data_path).expanduser())
        self._metadata_store = metadata_store
        self._repositories: list[SelectedRepository] = []
        self._history_offset: int = 0
        self._history_entries: list[HistoryEntry] = []

    @property
    def repositories(self) -> list[SelectedRepository]:
        return list(self._repositories)

    async def add_repository(self, path: str) -> SelectedRepository | None:
        """Add a repository and discover its sessions."""
        path = str(Path(path).resolve())
        if any(r.path == path for r in self._repositories):
            return None

        repo = await self._scan_repository(path)
        if repo is not None:
            self._repositories.append(repo)
        return repo

    async def add_repositories(self, paths: list[str]) -> None:
        for path in paths:
            await self.add_repository(path)

    async def remove_repository(self, path: str) -> None:
        self._repositories = [r for r in self._repositories if r.path != path]

    async def get_selected_repositories(self) -> list[SelectedRepository]:
        return list(self._repositories)

    async def set_selected_repositories(self, repositories: list[SelectedRepository]) -> None:
        self._repositories = list(repositories)

    async def refresh_sessions(self, *, skip_worktree_redetection: bool = False) -> None:
        """Re-scan all repositories for sessions."""
        await self._load_history()
        new_repos: list[SelectedRepository] = []
        for repo in self._repositories:
            refreshed = await self._scan_repository(
                repo.path, detect_worktrees=not skip_worktree_redetection
            )
            if refreshed is not None:
                new_repos.append(refreshed)
            else:
                new_repos.append(repo)
        self._repositories = new_repos

    async def _load_history(self) -> None:
        """Parse history.jsonl incrementally."""
        history_file = get_history_file(self._claude_path)
        if not history_file.is_file():
            return

        try:
            file_size = history_file.stat().st_size
            if file_size <= self._history_offset:
                return

            with open(history_file, "rb") as f:
                f.seek(self._history_offset)
                new_data = f.read()

            self._history_offset = file_size

            for line in new_data.decode("utf-8", errors="replace").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    if isinstance(data, dict):
                        entry = HistoryEntry(
                            display=str(data.get("display", "")),
                            timestamp=int(data.get("timestamp", 0)),
                            project=str(data.get("project", "")),
                            session_id=str(data.get("sessionId", data.get("session_id", ""))),
                        )
                        self._history_entries.append(entry)
                except (json.JSONDecodeError, ValueError, TypeError):
                    continue
        except OSError:
            logger.exception("Failed to read history file")

    async def _scan_repository(
        self, repo_path: str, detect_worktrees: bool = True
    ) -> SelectedRepository | None:
        """Scan a repository for sessions, optionally detecting worktrees."""
        path = Path(repo_path)
        if not path.is_dir():
            return None

        projects_dir = get_claude_projects_dir(self._claude_path)

        # Build lookup of previous sessions to avoid re-reading unchanged files
        previous_sessions: dict[str, CLISession] | None = None
        existing_repo = next((r for r in self._repositories if r.path == repo_path), None)
        if existing_repo is not None:
            previous_sessions = {
                s.id: s
                for wt in existing_repo.worktrees
                for s in wt.sessions
            }

        sessions = await self._find_sessions_for_path(
            repo_path, projects_dir, previous_sessions
        )

        # Detect worktrees
        worktrees: list[WorktreeBranch] = []
        if detect_worktrees:
            worktrees = await self._detect_worktrees(repo_path, sessions)
        else:
            # Single branch with all sessions
            worktrees = [
                WorktreeBranch(
                    name=path.name,
                    path=repo_path,
                    is_worktree=False,
                    sessions=sessions,
                    is_expanded=True,
                )
            ]

        return SelectedRepository(
            path=repo_path,
            name=path.name,
            worktrees=worktrees,
            is_expanded=True,
        )

    async def _find_sessions_for_path(
        self,
        repo_path: str,
        projects_dir: Path,
        previous_sessions: dict[str, CLISession] | None = None,
    ) -> list[CLISession]:
        """Find all sessions for a given repository path."""
        sessions: list[CLISession] = []

        # Look up encoded project path directory
        encoded = encode_project_path(repo_path)
        session_dir = projects_dir / encoded

        if session_dir.is_dir():
            for session_file in find_session_files(session_dir):
                session_id = session_id_from_path(session_file)
                now = datetime.now(tz=timezone.utc)

                # Check if active (mtime within threshold)
                mtime = 0.0
                try:
                    mtime = session_file.stat().st_mtime
                    elapsed = now.timestamp() - mtime
                    is_active = elapsed < _ACTIVE_THRESHOLD_SECONDS
                except OSError:
                    is_active = False

                # Parse head for slug and branch
                head_info = parse_session_head(str(session_file))

                # Find matching history entry for metadata
                history = next(
                    (h for h in self._history_entries if h.session_id == session_id),
                    None,
                )

                # Check if agent needs user attention.
                # If file hasn't changed since last scan, carry forward previous result.
                prev = previous_sessions.get(session_id) if previous_sessions else None
                if prev is not None and prev.last_activity_at.timestamp() == mtime:
                    attention = prev.needs_attention
                else:
                    attention = detect_needs_attention(session_file)

                session = CLISession(
                    id=session_id,
                    project_path=repo_path,
                    branch_name=head_info.get("git_branch", ""),
                    is_worktree=False,
                    last_activity_at=datetime.fromtimestamp(mtime, tz=timezone.utc)
                    if mtime
                    else now,
                    message_count=0,
                    is_active=is_active,
                    first_message=history.display if history else "",
                    slug=head_info.get("slug", ""),
                    session_file_path=str(session_file),
                    needs_attention=attention,
                )
                sessions.append(session)

        # Also check history entries that reference this path
        for entry in self._history_entries:
            if entry.project == repo_path:
                existing = any(s.id == entry.session_id for s in sessions)
                if not existing:
                    # Session from history but file may not be in expected location
                    sessions.append(
                        CLISession(
                            id=entry.session_id,
                            project_path=repo_path,
                            last_activity_at=entry.date,
                            first_message=entry.display,
                        )
                    )

        # Sort by last activity (most recent first)
        sessions.sort(key=lambda s: s.last_activity_at, reverse=True)
        return sessions

    async def _detect_worktrees(
        self, repo_path: str, sessions: list[CLISession]
    ) -> list[WorktreeBranch]:
        """Detect git worktrees for a repository."""
        import asyncio

        worktrees: list[WorktreeBranch] = []

        try:
            proc = await asyncio.create_subprocess_exec(
                "git", "-C", repo_path, "worktree", "list", "--porcelain",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()

            if proc.returncode != 0:
                # Not a git repo or no worktrees
                worktrees.append(
                    WorktreeBranch(
                        name=Path(repo_path).name,
                        path=repo_path,
                        is_worktree=False,
                        sessions=sessions,
                        is_expanded=True,
                    )
                )
                return worktrees

            # Parse porcelain output
            current_path = ""
            current_branch = ""
            for line in stdout.decode().splitlines():
                if line.startswith("worktree "):
                    current_path = line[len("worktree "):]
                elif line.startswith("branch "):
                    ref = line[len("branch "):]
                    current_branch = ref.split("/")[-1]
                elif line == "" and current_path:
                    # End of entry
                    is_wt = current_path != repo_path
                    wt_sessions = [
                        s for s in sessions
                        if s.project_path == current_path
                        or s.project_path.startswith(current_path + "/")
                        or s.branch_name == current_branch
                    ]

                    worktrees.append(
                        WorktreeBranch(
                            name=current_branch or Path(current_path).name,
                            path=current_path,
                            is_worktree=is_wt,
                            sessions=wt_sessions,
                            is_expanded=True,
                        )
                    )
                    current_path = ""
                    current_branch = ""

            # Handle last entry
            if current_path:
                is_wt = current_path != repo_path
                wt_sessions = [
                    s for s in sessions
                    if s.project_path == current_path
                    or s.project_path.startswith(current_path + "/")
                    or s.branch_name == current_branch
                ]
                worktrees.append(
                    WorktreeBranch(
                        name=current_branch or Path(current_path).name,
                        path=current_path,
                        is_worktree=is_wt,
                        sessions=wt_sessions,
                        is_expanded=True,
                    )
                )

            # Assign unmatched sessions to main worktree
            matched_ids = {s.id for wt in worktrees for s in wt.sessions}
            unmatched = [s for s in sessions if s.id not in matched_ids]
            if unmatched and worktrees:
                main_wt = worktrees[0]
                worktrees[0] = WorktreeBranch(
                    name=main_wt.name,
                    path=main_wt.path,
                    is_worktree=main_wt.is_worktree,
                    sessions=list(main_wt.sessions) + unmatched,
                    is_expanded=main_wt.is_expanded,
                )

        except (OSError, FileNotFoundError):
            worktrees.append(
                WorktreeBranch(
                    name=Path(repo_path).name,
                    path=repo_path,
                    is_worktree=False,
                    sessions=sessions,
                    is_expanded=True,
                )
            )

        return worktrees if worktrees else [
            WorktreeBranch(
                name=Path(repo_path).name,
                path=repo_path,
                is_worktree=False,
                sessions=sessions,
                is_expanded=True,
            )
        ]
