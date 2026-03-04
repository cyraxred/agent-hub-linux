"""AgentHubProvider — service locator for all application services."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from agent_hub.config.settings import Settings
from agent_hub.services.cli_session_monitor import CLISessionMonitorService
from agent_hub.services.codex_file_watcher import CodexSessionFileWatcher
from agent_hub.services.codex_search_service import CodexSearchService
from agent_hub.services.codex_session_monitor import CodexSessionMonitorService
from agent_hub.services.codex_stats_service import CodexGlobalStatsService
from agent_hub.services.dev_server_manager import DevServerManager
from agent_hub.services.global_search_service import GlobalSearchService
from agent_hub.services.global_stats_service import GlobalStatsService
from agent_hub.services.metadata_store import MetadataStore
from agent_hub.services.process_registry import ProcessRegistry
from agent_hub.services.session_file_watcher import SessionFileWatcher
from agent_hub.services.session_parse_cache import SessionParseCache

if TYPE_CHECKING:
    from agent_hub.services import git_worktree_service as _git_mod

logger = logging.getLogger(__name__)


def _resolve_encoded_path(encoded: str) -> str | None:
    """Resolve a Claude-encoded project folder name back to a real filesystem path.

    Claude encodes paths by stripping the leading ``/`` and replacing every
    ``/`` with ``-``.  This is ambiguous when directory names contain dashes.

    We greedily walk the encoded segments: at each step we try extending the
    current component with a ``-`` (i.e. the dash was literal) before trying
    a ``/`` (i.e. the dash was a separator).  This prefers longer directory
    names, which resolves the ambiguity for names like ``agent-hub-linux``.
    """
    from pathlib import Path

    if not encoded or encoded == "-":
        return "/"

    # Strip leading dash(es) that represent the root /
    stripped = encoded.lstrip("-")
    parts = stripped.split("-")
    if not parts:
        return None

    def _walk(idx: int, current: str) -> str | None:
        if idx == len(parts):
            return current if Path(current).is_dir() else None

        # Try greedily joining with dash first (literal dash in name)
        # by looking ahead and combining multiple segments.
        # We try longest match first to prefer "agent-hub-linux" over "agent/hub/linux".
        for end in range(len(parts), idx, -1):
            candidate_segment = "-".join(parts[idx:end])
            candidate_path = current + "/" + candidate_segment
            if Path(candidate_path).is_dir():
                result = _walk(end, candidate_path)
                if result is not None:
                    return result

        return None

    return _walk(0, "")


class AgentHubProvider:
    """Lazy-initialising service locator for the entire application.

    All service properties create their instance on first access and cache it
    for subsequent calls.  Call :meth:`init` once at startup and :meth:`shutdown`
    once at teardown.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

        # Private backing stores — ``None`` means "not yet created"
        self._claude_monitor: CLISessionMonitorService | None = None
        self._codex_monitor: CodexSessionMonitorService | None = None
        self._claude_watcher: SessionFileWatcher | None = None
        self._codex_watcher: CodexSessionFileWatcher | None = None
        self._parse_cache: SessionParseCache | None = None
        self._git_service_module: _git_mod | None = None
        self._stats_service: GlobalStatsService | None = None
        self._codex_stats_service: CodexGlobalStatsService | None = None
        self._claude_search: GlobalSearchService | None = None
        self._codex_search: CodexSearchService | None = None
        self._metadata_store: MetadataStore | None = None
        self._process_registry: ProcessRegistry | None = None
        self._dev_server_manager: DevServerManager | None = None

    # ------------------------------------------------------------------
    # Read-only access to settings
    # ------------------------------------------------------------------

    @property
    def settings(self) -> Settings:
        return self._settings

    # ------------------------------------------------------------------
    # Lazy service properties
    # ------------------------------------------------------------------

    @property
    def claude_monitor(self) -> CLISessionMonitorService:
        if self._claude_monitor is None:
            self._claude_monitor = CLISessionMonitorService(
                claude_data_path=self._settings.claude_data_path,
                metadata_store=self.metadata_store,
            )
        return self._claude_monitor

    @property
    def codex_monitor(self) -> CodexSessionMonitorService:
        if self._codex_monitor is None:
            self._codex_monitor = CodexSessionMonitorService(
                codex_data_path=self._settings.codex_data_path,
            )
        return self._codex_monitor

    @property
    def parse_cache(self) -> SessionParseCache:
        if self._parse_cache is None:
            self._parse_cache = SessionParseCache(
                max_size=256,
                approval_timeout_seconds=self._settings.approval_timeout_seconds,
            )
        return self._parse_cache

    @property
    def claude_watcher(self) -> SessionFileWatcher:
        if self._claude_watcher is None:
            self._claude_watcher = SessionFileWatcher(
                claude_path=self._settings.claude_data_path,
                approval_timeout_seconds=self._settings.approval_timeout_seconds,
                parse_cache=self.parse_cache,
            )
        return self._claude_watcher

    @property
    def codex_watcher(self) -> CodexSessionFileWatcher:
        if self._codex_watcher is None:
            self._codex_watcher = CodexSessionFileWatcher(
                codex_path=self._settings.codex_data_path,
                approval_timeout_seconds=self._settings.approval_timeout_seconds,
                parse_cache=self.parse_cache,
            )
        return self._codex_watcher

    @property
    def git_service(self) -> _git_mod:
        """Return the ``git_worktree_service`` module (used as a namespace)."""
        if self._git_service_module is None:
            from agent_hub.services import git_worktree_service

            self._git_service_module = git_worktree_service  # type: ignore[assignment]
        return self._git_service_module  # type: ignore[return-value]

    @property
    def stats_service(self) -> GlobalStatsService:
        if self._stats_service is None:
            self._stats_service = GlobalStatsService(
                claude_data_path=self._settings.claude_data_path,
            )
        return self._stats_service

    @property
    def codex_stats_service(self) -> CodexGlobalStatsService:
        if self._codex_stats_service is None:
            self._codex_stats_service = CodexGlobalStatsService(
                codex_data_path=self._settings.codex_data_path,
            )
        return self._codex_stats_service

    @property
    def claude_search(self) -> GlobalSearchService:
        if self._claude_search is None:
            self._claude_search = GlobalSearchService(
                claude_data_path=self._settings.claude_data_path,
            )
        return self._claude_search

    @property
    def codex_search(self) -> CodexSearchService:
        if self._codex_search is None:
            self._codex_search = CodexSearchService(
                codex_data_path=self._settings.codex_data_path,
            )
        return self._codex_search

    @property
    def metadata_store(self) -> MetadataStore:
        if self._metadata_store is None:
            self._metadata_store = MetadataStore(
                db_path=self._settings.db_path,
            )
        return self._metadata_store

    @property
    def process_registry(self) -> ProcessRegistry:
        if self._process_registry is None:
            self._process_registry = ProcessRegistry()
        return self._process_registry

    @property
    def dev_server_manager(self) -> DevServerManager:
        if self._dev_server_manager is None:
            self._dev_server_manager = DevServerManager()
        return self._dev_server_manager

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def init(self) -> None:
        """Initialise the database and start background watchers."""
        logger.info("Initialising AgentHubProvider...")

        # 1. Database
        await self.metadata_store.init_db()
        logger.info("MetadataStore initialised (db=%s)", self._settings.db_path)

        # 2. Stats watcher (Claude) — starts its own file observer
        await self.stats_service.start()
        logger.info("GlobalStatsService started")

        # 3. Codex stats — initial scan (no observer, just compute once)
        await self.codex_stats_service.refresh()
        logger.info("CodexGlobalStatsService refreshed")

        # 4. Build search indexes
        await self.claude_search.rebuild_index()
        indexed_count = await self.claude_search.indexed_session_count()
        logger.info("Claude search index built (%d sessions)", indexed_count)

        await self.codex_search.rebuild_index()
        codex_indexed = await self.codex_search.indexed_session_count()
        logger.info("Codex search index built (%d sessions)", codex_indexed)

        # 5. Auto-discover repositories from session files
        await self._auto_discover_repositories()

        logger.info("AgentHubProvider initialised successfully.")

    async def _auto_discover_repositories(self) -> None:
        """Auto-discover repositories from existing session files.

        Scans ~/.claude/projects/ for encoded project directories and adds
        any that correspond to real directories on disk.

        Because Claude's path encoding is lossy (``/`` and ``-`` both become
        ``-``), we cannot reliably *decode* a folder name back to a filesystem
        path.  Instead we try progressively resolving the encoded name: split
        on ``-``, then greedily re-join segments with ``-`` where a real
        directory exists on disk.
        """
        from agent_hub.services.path_utils import (
            encode_project_path,
            get_claude_projects_dir,
        )
        from pathlib import Path

        projects_dir = get_claude_projects_dir(self._settings.claude_data_path)
        if not projects_dir.is_dir():
            return

        discovered: set[str] = set()
        for child in projects_dir.iterdir():
            if not child.is_dir():
                continue
            has_sessions = any(child.glob("*.jsonl"))
            if not has_sessions:
                continue
            resolved = _resolve_encoded_path(child.name)
            if resolved and Path(resolved).is_dir():
                # Double-check by re-encoding to make sure it matches
                if encode_project_path(resolved) == child.name:
                    discovered.add(resolved)

        if discovered:
            await self.claude_monitor.add_repositories(sorted(discovered))
            logger.info(
                "Auto-discovered %d Claude repositories: %s",
                len(discovered),
                [str(p) for p in sorted(discovered)],
            )

    async def shutdown(self) -> None:
        """Gracefully stop all background work and release resources."""
        logger.info("Shutting down AgentHubProvider...")

        # File watchers
        if self._claude_watcher is not None:
            await self._claude_watcher.shutdown()
            logger.debug("Claude watcher stopped")
        if self._codex_watcher is not None:
            await self._codex_watcher.shutdown()
            logger.debug("Codex watcher stopped")

        # Stats watchers
        if self._stats_service is not None:
            await self._stats_service.stop()
            logger.debug("Stats service stopped")

        # Dev servers
        if self._dev_server_manager is not None:
            await self._dev_server_manager.stop_all()
            logger.debug("Dev servers stopped")

        # Process registry
        if self._process_registry is not None:
            self._process_registry.terminate_all()
            logger.debug("Process registry cleaned up")

        # Database
        if self._metadata_store is not None:
            await self._metadata_store.close()
            logger.debug("MetadataStore closed")

        logger.info("AgentHubProvider shutdown complete.")
