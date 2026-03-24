"""AgentHubProvider — service locator for all application services."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from agent_hub.config.settings import Settings
from agent_hub.services.codex_search_service import CodexSearchService
from agent_hub.services.codex_stats_service import CodexGlobalStatsService
from agent_hub.services.dev_server_manager import DevServerManager
from agent_hub.services.file_watcher import FileWatcher
from agent_hub.services.global_search_service import GlobalSearchService
from agent_hub.services.global_stats_service import GlobalStatsService
from agent_hub.services.metadata_store import MetadataStore
from agent_hub.services.claude_process_tracker import ClaudeProcessTracker
from agent_hub.services.process_registry import ProcessRegistry
from agent_hub.services.session_manager import SessionManager
from agent_hub.services.session_parse_cache import SessionParseCache
from agent_hub.services.transcript_registry import TranscriptRegistry

if TYPE_CHECKING:
    from agent_hub.services import git_worktree_service as _git_mod
    from agent_hub.services.auth_service import AuthService
    from agent_hub.services.credential_store import CredentialStore

logger = logging.getLogger(__name__)



# resolve_encoded_path is now in path_utils


class AgentHubProvider:
    """Lazy-initialising service locator for the entire application.

    All service properties create their instance on first access and cache it
    for subsequent calls.  Call :meth:`init` once at startup and :meth:`shutdown`
    once at teardown.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

        # Private backing stores — ``None`` means "not yet created"
        self._parse_cache: SessionParseCache | None = None
        self._git_service_module: _git_mod | None = None
        self._stats_service: GlobalStatsService | None = None
        self._codex_stats_service: CodexGlobalStatsService | None = None
        self._claude_search: GlobalSearchService | None = None
        self._codex_search: CodexSearchService | None = None
        self._metadata_store: MetadataStore | None = None
        self._process_registry: ProcessRegistry | None = None
        self._process_tracker: ClaudeProcessTracker | None = None
        self._session_manager: SessionManager | None = None
        self._dev_server_manager: DevServerManager | None = None
        self._auth_service: AuthService | None = None
        self._credential_store: CredentialStore | None = None
        self._proxy_service: object | None = None  # ProxyService — imported lazily
        self._file_watcher: FileWatcher | None = None
        self._claude_transcript_registry: TranscriptRegistry | None = None
        self._codex_transcript_registry: TranscriptRegistry | None = None

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
    def parse_cache(self) -> SessionParseCache:
        if self._parse_cache is None:
            self._parse_cache = SessionParseCache(
                max_size=256,
                approval_timeout_seconds=self._settings.approval_timeout_seconds,
            )
        return self._parse_cache

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
    def auth_service(self) -> AuthService:
        if self._auth_service is None:
            from agent_hub.services.auth_service import AuthService

            self._auth_service = AuthService(self.metadata_store)
        return self._auth_service

    @property
    def credential_store(self) -> CredentialStore:
        if self._credential_store is None:
            from agent_hub.services.credential_store import CredentialStore

            self._credential_store = CredentialStore(self._settings.app_data_dir)
        return self._credential_store

    @property
    def process_registry(self) -> ProcessRegistry:
        if self._process_registry is None:
            self._process_registry = ProcessRegistry()
        return self._process_registry

    @property
    def process_tracker(self) -> ClaudeProcessTracker:
        if self._process_tracker is None:
            self._process_tracker = ClaudeProcessTracker(
                claude_data_path=self._settings.claude_data_path,
                process_registry=self.process_registry,
            )
        return self._process_tracker

    @property
    def session_manager(self) -> SessionManager:
        if self._session_manager is None:
            self._session_manager = SessionManager()
        return self._session_manager

    @property
    def proxy_service(self) -> object:
        """Return the :class:`~agent_hub.services.proxy_service.ProxyService` singleton."""
        if self._proxy_service is None:
            from agent_hub.services.proxy_service import ProxyService

            self._proxy_service = ProxyService()
        return self._proxy_service

    @property
    def dev_server_manager(self) -> DevServerManager:
        if self._dev_server_manager is None:
            self._dev_server_manager = DevServerManager()
        return self._dev_server_manager

    @property
    def file_watcher(self) -> FileWatcher:
        if self._file_watcher is None:
            self._file_watcher = FileWatcher.get_instance()
        return self._file_watcher

    @property
    def claude_transcript_registry(self) -> TranscriptRegistry:
        if self._claude_transcript_registry is None:
            from agent_hub.services.session_jsonl_parser import (
                ParseResult as ClaudeParseResult,
                parse_new_lines as claude_parse_new_lines,
            )

            self._claude_transcript_registry = TranscriptRegistry(
                provider="claude",
                parse_fn=claude_parse_new_lines,
                parse_result_factory=ClaudeParseResult,
                approval_timeout_seconds=self._settings.approval_timeout_seconds,
                parse_cache=self.parse_cache,
                file_watcher=self.file_watcher,
            )
        return self._claude_transcript_registry

    @property
    def codex_transcript_registry(self) -> TranscriptRegistry:
        if self._codex_transcript_registry is None:
            from agent_hub.services.codex_jsonl_parser import (
                ParseResult as CodexParseResult,
                parse_new_lines as codex_parse_new_lines,
            )

            self._codex_transcript_registry = TranscriptRegistry(
                provider="codex",
                parse_fn=codex_parse_new_lines,
                parse_result_factory=CodexParseResult,
                approval_timeout_seconds=self._settings.approval_timeout_seconds,
                parse_cache=self.parse_cache,
                file_watcher=self.file_watcher,
            )
        return self._codex_transcript_registry

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def init(self) -> None:
        """Initialise the database and start background watchers."""
        import asyncio

        logger.info("Initialising AgentHubProvider...")

        # 0. Set the event loop on the singleton FileWatcher
        self.file_watcher.set_loop(asyncio.get_event_loop())

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

        # 5. Install session hooks and start process tracker
        try:
            from agent_hub.services.hook_installer import ensure_hooks_installed

            ensure_hooks_installed(self._settings.claude_data_path)
            logger.info("Session hooks installed")
        except Exception:
            logger.exception("Failed to install session hooks")

        await self.process_tracker.start()
        logger.info("ClaudeProcessTracker started")

        # 6. Start transcript registries and wire into SessionManager
        await self.claude_transcript_registry.start()
        await self.codex_transcript_registry.start()
        logger.info("Transcript registries started")

        await self.session_manager.start()
        self.session_manager.set_tracker(self.process_tracker)
        self.session_manager.set_process_registry(self.process_registry)
        self.session_manager.set_transcript_registry(
            claude_registry=self.claude_transcript_registry,
            codex_registry=self.codex_transcript_registry,
            claude_data_path=self._settings.claude_data_path,
        )

        # Wire transcript registry → SessionManager callbacks BEFORE discovery
        # so that initially discovered transcripts create Session entries.
        sm = self.session_manager
        for registry in (self.claude_transcript_registry, self.codex_transcript_registry):
            registry.on_state_update(sm.handle_monitor_state_update)
            registry.on_transcript_added(sm.handle_transcript_added)
            registry.on_transcript_removed(sm.handle_transcript_removed)

        # Now discover — register_transcript is awaited directly, so
        # SessionManager is populated before init() returns.
        await self._auto_discover_project_directories()
        logger.info("SessionManager started (%d sessions)", len(sm._sessions))

        logger.info("AgentHubProvider initialised successfully.")

    async def _auto_discover_project_directories(self) -> None:
        """Register all existing project directories with the transcript registry.

        Scans ~/.claude/projects/ and registers each subdirectory.
        ``add_project_directory`` is async — it awaits the initial file
        enumeration so all existing transcripts are discovered and
        registered (via callbacks) before this method returns.
        """
        from pathlib import Path

        from agent_hub.services.path_utils import get_claude_projects_dir

        projects_dir = get_claude_projects_dir(self._settings.claude_data_path)
        if not projects_dir.is_dir():
            return

        registry = self.claude_transcript_registry
        count = 0

        for child in projects_dir.iterdir():
            if not child.is_dir():
                continue
            await registry.add_project_directory(str(child))
            count += 1

        if count:
            logger.info("Registered %d project directories with transcript registry", count)

    async def shutdown(self) -> None:
        """Gracefully stop all background work and release resources."""
        logger.info("Shutting down AgentHubProvider...")

        # Transcript registries (before file watcher)
        if self._claude_transcript_registry is not None:
            await self._claude_transcript_registry.stop()
            logger.debug("Claude transcript registry stopped")
        if self._codex_transcript_registry is not None:
            await self._codex_transcript_registry.stop()
            logger.debug("Codex transcript registry stopped")

        # Stats watchers
        if self._stats_service is not None:
            await self._stats_service.stop()
            logger.debug("Stats service stopped")

        # Dev servers
        if self._dev_server_manager is not None:
            await self._dev_server_manager.stop_all()
            logger.debug("Dev servers stopped")

        # Session manager (before process tracker)
        if self._session_manager is not None:
            await self._session_manager.stop()
            logger.debug("Session manager stopped")

        # Process tracker (before process registry cleanup)
        if self._process_tracker is not None:
            await self._process_tracker.stop()
            logger.debug("Process tracker stopped")

        # Process registry
        if self._process_registry is not None:
            self._process_registry.terminate_all()
            logger.debug("Process registry cleaned up")

        # Proxy service (remote host connections)
        if self._proxy_service is not None:
            from agent_hub.services.proxy_service import ProxyService

            await ProxyService.shutdown(self._proxy_service)  # type: ignore[arg-type]
            logger.debug("ProxyService shut down")

        # Database
        if self._metadata_store is not None:
            await self._metadata_store.close()
            logger.debug("MetadataStore closed")

        # FileWatcher singleton (last — all consumers must be stopped first)
        if self._file_watcher is not None:
            self._file_watcher.shutdown()
            logger.debug("FileWatcher stopped")

        logger.info("AgentHubProvider shutdown complete.")
