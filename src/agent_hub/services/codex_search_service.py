"""Search service for Codex sessions."""

from __future__ import annotations

from agent_hub.models.search import SessionSearchResult
from agent_hub.services.global_search_service import GlobalSearchService


class CodexSearchService(GlobalSearchService):
    """In-memory search index over Codex session history."""

    def __init__(self, codex_data_path: str = "~/.codex") -> None:
        super().__init__(claude_data_path=codex_data_path)
