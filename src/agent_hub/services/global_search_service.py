"""In-memory session search index for Claude sessions."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from agent_hub.models.search import (
    SearchMatchField,
    SessionIndexEntry,
    SessionSearchResult,
)
from agent_hub.services.path_utils import (
    find_session_files,
    get_claude_projects_dir,
    get_history_file,
    project_path_from_session_dir,
    session_id_from_path,
)
from agent_hub.services.search_scoring import score

logger = logging.getLogger(__name__)

# Field scoring bonuses
_FIELD_BONUS: dict[SearchMatchField, int] = {
    SearchMatchField.slug: 20,
    SearchMatchField.summary: 15,
    SearchMatchField.path: 10,
    SearchMatchField.git_branch: 10,
    SearchMatchField.first_message: 5,
}


class GlobalSearchService:
    """In-memory search index over Claude session history."""

    def __init__(self, claude_data_path: str = "~/.claude") -> None:
        self._claude_path = str(Path(claude_data_path).expanduser())
        self._index: list[SessionIndexEntry] = []

    async def rebuild_index(self) -> None:
        """Rebuild the search index from scratch."""
        self._index.clear()
        projects_dir = get_claude_projects_dir(self._claude_path)
        history = self._load_history()

        session_files = find_session_files(projects_dir)
        for sf in session_files:
            session_id = session_id_from_path(sf)
            project_path = project_path_from_session_dir(sf.parent, projects_dir)

            hist_entry = history.get(session_id)
            slug = ""
            first_message = hist_entry.get("display", "") if hist_entry else ""

            # Read first few lines for slug/branch
            git_branch = ""
            try:
                with open(sf, encoding="utf-8", errors="replace") as f:
                    head = f.read(8192)
                for line in head.splitlines():
                    if not line.strip():
                        continue
                    try:
                        data = json.loads(line)
                        if isinstance(data, dict):
                            s = data.get("slug")
                            if isinstance(s, str) and s:
                                slug = s
                    except json.JSONDecodeError:
                        continue
            except OSError:
                continue

            try:
                mtime = sf.stat().st_mtime
                last_activity = datetime.fromtimestamp(mtime, tz=timezone.utc)
            except OSError:
                last_activity = datetime.now(tz=timezone.utc)

            self._index.append(
                SessionIndexEntry(
                    session_id=session_id,
                    project_path=project_path,
                    slug=slug,
                    git_branch=git_branch,
                    first_message=first_message,
                    summaries=[],
                    last_activity_at=last_activity,
                )
            )

    async def indexed_session_count(self) -> int:
        return len(self._index)

    async def search(
        self, query: str, filter_path: str | None = None
    ) -> list[SessionSearchResult]:
        """Search for sessions matching the query."""
        if not query.strip():
            return []

        results: list[SessionSearchResult] = []
        for entry in self._index:
            if filter_path and not entry.project_path.startswith(filter_path):
                continue

            best_result: SessionSearchResult | None = None
            best_score = 0

            # Score against each field
            for field_name, bonus in _FIELD_BONUS.items():
                text = self._get_field_text(entry, field_name)
                if not text:
                    continue
                match = score(query, text)
                if match is not None:
                    total = match.score + bonus
                    if total > best_score:
                        best_score = total
                        best_result = SessionSearchResult(
                            id=entry.session_id,
                            slug=entry.slug,
                            project_path=entry.project_path,
                            git_branch=entry.git_branch,
                            first_message=entry.first_message,
                            summaries=entry.summaries,
                            last_activity_at=entry.last_activity_at,
                            matched_field=field_name,
                            matched_text=text,
                            relevance_score=total,
                        )

            if best_result is not None:
                results.append(best_result)

        results.sort(key=lambda r: r.relevance_score, reverse=True)
        return results[:50]

    def _get_field_text(self, entry: SessionIndexEntry, field: SearchMatchField) -> str:
        if field == SearchMatchField.slug:
            return entry.slug
        elif field == SearchMatchField.path:
            return entry.project_path
        elif field == SearchMatchField.git_branch:
            return entry.git_branch or ""
        elif field == SearchMatchField.first_message:
            return entry.first_message or ""
        elif field == SearchMatchField.summary:
            return " ".join(entry.summaries)
        return ""

    def _load_history(self) -> dict[str, dict[str, str]]:
        """Load history.jsonl into a lookup dict."""
        result: dict[str, dict[str, str]] = {}
        history_file = get_history_file(self._claude_path)
        if not history_file.is_file():
            return result
        try:
            with open(history_file, encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        if isinstance(data, dict):
                            sid = str(data.get("sessionId", data.get("session_id", "")))
                            if sid:
                                result[sid] = {
                                    "display": str(data.get("display", "")),
                                    "project": str(data.get("project", "")),
                                }
                    except json.JSONDecodeError:
                        continue
        except OSError:
            pass
        return result
