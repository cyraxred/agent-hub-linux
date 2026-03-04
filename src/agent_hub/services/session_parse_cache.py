"""LRU cache for parsed session JSONL files.

Stores ParseResult + file metadata so that non-monitored sessions can
be queried without re-parsing unchanged files.  Monitored sessions
write-through on every incremental update, keeping the cache warm
after monitoring stops.
"""

from __future__ import annotations

import logging
import threading
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Union

from agent_hub.services.codex_jsonl_parser import ParseResult as CodexParseResult
from agent_hub.services.codex_jsonl_parser import parse_session_file as _codex_parse_session_file
from agent_hub.services.codex_jsonl_parser import update_current_status as _codex_update_current_status
from agent_hub.services.session_jsonl_parser import ParseResult as ClaudeParseResult
from agent_hub.services.session_jsonl_parser import parse_session_file as _claude_parse_session_file
from agent_hub.services.session_jsonl_parser import (
    update_current_status as _claude_update_current_status,
)

logger = logging.getLogger(__name__)

ParseResultUnion = Union[ClaudeParseResult, CodexParseResult]


@dataclass
class _CacheEntry:
    """A single cached parse result with metadata for invalidation."""

    session_id: str
    file_path: str
    file_size: int
    parse_result: ParseResultUnion
    provider: str


class SessionParseCache:
    """Thread-safe LRU cache for session parse results.

    Keyed by ``"provider:session_id"``.  Invalidated by *file_size*
    (JSONL is append-only so size is monotonically increasing).
    Status is re-evaluated on every read because it depends on
    wall-clock time, not file content.
    """

    def __init__(
        self,
        max_size: int = 256,
        approval_timeout_seconds: int = 5,
    ) -> None:
        self._max_size = max_size
        self._approval_timeout_seconds = approval_timeout_seconds
        self._cache: OrderedDict[str, _CacheEntry] = OrderedDict()
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @staticmethod
    def _key(session_id: str, provider: str) -> str:
        return f"{provider}:{session_id}"

    def get(
        self,
        session_id: str,
        file_path: str,
        provider: str = "claude",
    ) -> ParseResultUnion | None:
        """Return cached parse result, re-parsing if the file has grown.

        On cache hit with unchanged file_size, re-evaluates
        time-dependent status (O(1)) and returns the cached result.
        On cache miss or stale entry, performs a full parse.
        Returns ``None`` only if the file cannot be read.
        """
        key = self._key(session_id, provider)
        path = Path(file_path)

        try:
            current_size = path.stat().st_size
        except OSError:
            return None

        with self._lock:
            entry = self._cache.get(key)
            if entry is not None and entry.file_size == current_size:
                self._cache.move_to_end(key)
                self._refresh_status(entry)
                return entry.parse_result

        # Cache miss or stale — full parse (outside lock to avoid blocking)
        parse_result = self._full_parse(file_path, provider)
        if parse_result is None:
            return None

        with self._lock:
            self._cache[key] = _CacheEntry(
                session_id=session_id,
                file_path=file_path,
                file_size=current_size,
                parse_result=parse_result,
                provider=provider,
            )
            self._cache.move_to_end(key)
            self._evict_if_needed()

        return parse_result

    def put(
        self,
        session_id: str,
        file_path: str,
        file_size: int,
        parse_result: ParseResultUnion,
        provider: str = "claude",
    ) -> None:
        """Write-through: store / update a parse result from incremental monitoring."""
        key = self._key(session_id, provider)
        with self._lock:
            self._cache[key] = _CacheEntry(
                session_id=session_id,
                file_path=file_path,
                file_size=file_size,
                parse_result=parse_result,
                provider=provider,
            )
            self._cache.move_to_end(key)
            self._evict_if_needed()

    def invalidate(self, session_id: str, provider: str = "claude") -> None:
        """Remove a specific entry from the cache."""
        key = self._key(session_id, provider)
        with self._lock:
            self._cache.pop(key, None)

    def clear(self) -> None:
        """Drop all cached entries."""
        with self._lock:
            self._cache.clear()

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._cache)

    def set_approval_timeout(self, seconds: int) -> None:
        self._approval_timeout_seconds = seconds

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _evict_if_needed(self) -> None:
        """Evict oldest entries if over capacity.  Caller must hold lock."""
        while len(self._cache) > self._max_size:
            self._cache.popitem(last=False)

    def _refresh_status(self, entry: _CacheEntry) -> None:
        """Re-evaluate time-dependent status on a cached entry (O(1))."""
        if entry.provider == "codex":
            _codex_update_current_status(
                entry.parse_result,  # type: ignore[arg-type]
                self._approval_timeout_seconds,
            )
        else:
            _claude_update_current_status(
                entry.parse_result,  # type: ignore[arg-type]
                self._approval_timeout_seconds,
            )

    def _full_parse(
        self,
        file_path: str,
        provider: str,
    ) -> ParseResultUnion | None:
        """Perform a full parse of a session file."""
        try:
            if provider == "codex":
                return _codex_parse_session_file(file_path, self._approval_timeout_seconds)
            return _claude_parse_session_file(file_path, self._approval_timeout_seconds)
        except Exception:
            logger.exception("Failed to parse session file: %s", file_path)
            return None
