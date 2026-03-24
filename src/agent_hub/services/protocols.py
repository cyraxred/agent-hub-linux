"""Service protocol definitions ported from Swift SessionProviderProtocols.swift."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from agent_hub.models.monitor_state import SessionMonitorState
from agent_hub.models.search import SessionSearchResult
from agent_hub.models.session import SelectedRepository


@runtime_checkable
class SessionMonitorServiceProtocol(Protocol):
    """Protocol for session monitor services (Claude / Codex)."""

    async def add_repository(self, path: str) -> SelectedRepository | None:
        """Add a repository to monitor."""
        ...

    async def add_repositories(self, paths: list[str]) -> None:
        """Add multiple repositories to monitor."""
        ...

    async def remove_repository(self, path: str) -> None:
        """Remove a repository from monitoring."""
        ...

    async def get_selected_repositories(self) -> list[SelectedRepository]:
        """Get all currently selected repositories."""
        ...

    async def set_selected_repositories(
        self, repositories: list[SelectedRepository]
    ) -> None:
        """Replace the selected repositories list."""
        ...

    async def refresh_sessions(self, *, skip_worktree_redetection: bool = False) -> None:
        """Refresh session data, optionally skipping worktree re-detection."""
        ...


@runtime_checkable
class TranscriptRegistryProtocol(Protocol):
    """Protocol for transcript registry services."""

    def get_transcript(self, session_id: str) -> object | None:
        """Return the transcript for a session, or None."""
        ...

    def get_all_transcripts(self) -> list[object]:
        """Return all confirmed transcripts."""
        ...

    def set_monitored(self, session_id: str, monitored: bool) -> None:
        """Set per-file monitoring for a session."""
        ...

    async def add_project_directory(self, path: str) -> None:
        """Start watching a project directory."""
        ...

    def remove_project_directory(self, path: str) -> None:
        """Stop watching a project directory."""
        ...


@runtime_checkable
class SessionSearchServiceProtocol(Protocol):
    """Protocol for searching sessions."""

    async def search(
        self, query: str, filter_path: str | None = None
    ) -> list[SessionSearchResult]:
        """Search for sessions matching the query."""
        ...

    async def rebuild_index(self) -> None:
        """Rebuild the search index."""
        ...

    async def indexed_session_count(self) -> int:
        """Get the number of indexed sessions."""
        ...
