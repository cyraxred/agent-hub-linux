"""Codex session discovery service."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from agent_hub.models.session import CLISession, HistoryEntry, SelectedRepository, WorktreeBranch
from agent_hub.services.path_utils import get_history_file

logger = logging.getLogger(__name__)

_ACTIVE_THRESHOLD_SECONDS = 60.0


class CodexSessionMonitorService:
    """Discovers and manages Codex CLI sessions."""

    def __init__(self, codex_data_path: str = "~/.codex") -> None:
        self._codex_path = str(Path(codex_data_path).expanduser())
        self._repositories: list[SelectedRepository] = []
        self._history_offset: int = 0
        self._history_entries: list[HistoryEntry] = []

    @property
    def repositories(self) -> list[SelectedRepository]:
        return list(self._repositories)

    async def add_repository(self, path: str) -> SelectedRepository | None:
        path = str(Path(path).resolve())
        if any(r.path == path for r in self._repositories):
            return None
        repo = await self._scan_repository(path)
        if repo is not None:
            self._repositories.append(repo)
        return repo

    async def add_repositories(self, paths: list[str]) -> None:
        for p in paths:
            await self.add_repository(p)

    async def remove_repository(self, path: str) -> None:
        self._repositories = [r for r in self._repositories if r.path != path]

    async def get_selected_repositories(self) -> list[SelectedRepository]:
        return list(self._repositories)

    async def set_selected_repositories(self, repositories: list[SelectedRepository]) -> None:
        self._repositories = list(repositories)

    async def refresh_sessions(self, *, skip_worktree_redetection: bool = False) -> None:
        await self._load_history()
        new_repos: list[SelectedRepository] = []
        for repo in self._repositories:
            refreshed = await self._scan_repository(repo.path)
            new_repos.append(refreshed if refreshed else repo)
        self._repositories = new_repos

    async def _load_history(self) -> None:
        history_file = get_history_file(self._codex_path)
        if not history_file.is_file():
            return
        try:
            size = history_file.stat().st_size
            if size <= self._history_offset:
                return
            with open(history_file, "rb") as f:
                f.seek(self._history_offset)
                new_data = f.read()
            self._history_offset = size
            for line in new_data.decode("utf-8", errors="replace").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    if isinstance(data, dict):
                        self._history_entries.append(
                            HistoryEntry(
                                display=str(data.get("display", "")),
                                timestamp=int(data.get("timestamp", 0)),
                                project=str(data.get("project", "")),
                                session_id=str(
                                    data.get("sessionId", data.get("session_id", ""))
                                ),
                            )
                        )
                except (json.JSONDecodeError, ValueError, TypeError):
                    continue
        except OSError:
            logger.exception("Failed to read Codex history file")

    async def _scan_repository(self, repo_path: str) -> SelectedRepository | None:
        path = Path(repo_path)
        if not path.is_dir():
            return None

        sessions = self._find_sessions_for_path(repo_path)
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

    def _find_sessions_for_path(self, repo_path: str) -> list[CLISession]:
        sessions: list[CLISession] = []
        sessions_dir = Path(self._codex_path) / "sessions"
        now = datetime.now(tz=timezone.utc)

        if sessions_dir.is_dir():
            for date_dir in sorted(sessions_dir.iterdir(), reverse=True):
                if not date_dir.is_dir():
                    continue
                for sf in date_dir.glob("*.jsonl"):
                    session_id = sf.stem
                    try:
                        mtime = sf.stat().st_mtime
                        is_active = (now.timestamp() - mtime) < _ACTIVE_THRESHOLD_SECONDS
                    except OSError:
                        mtime = now.timestamp()
                        is_active = False

                    history = next(
                        (h for h in self._history_entries if h.session_id == session_id),
                        None,
                    )
                    if history and history.project != repo_path:
                        continue

                    sessions.append(
                        CLISession(
                            id=session_id,
                            project_path=repo_path,
                            last_activity_at=datetime.fromtimestamp(mtime, tz=timezone.utc),
                            is_active=is_active,
                            first_message=history.display if history else "",
                            session_file_path=str(sf),
                        )
                    )

        sessions.sort(key=lambda s: s.last_activity_at, reverse=True)
        return sessions
