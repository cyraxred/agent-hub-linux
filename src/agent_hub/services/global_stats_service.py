"""Global stats service — watches stats-cache.json for Claude."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from watchdog.events import FileModifiedEvent, FileSystemEventHandler
from watchdog.observers import Observer

from agent_hub.models.stats import (
    DailyActivity,
    DailyModelTokens,
    GlobalStatsCache,
    LongestSession,
    ModelUsage,
)
from agent_hub.services.path_utils import get_stats_cache_file

logger = logging.getLogger(__name__)


class GlobalStatsService:
    """Watches and parses Claude stats-cache.json."""

    def __init__(self, claude_data_path: str = "~/.claude") -> None:
        self._claude_path = str(Path(claude_data_path).expanduser())
        self._stats: GlobalStatsCache | None = None
        self._observer: Observer | None = None
        self._callbacks: list[object] = []

    @property
    def stats(self) -> GlobalStatsCache | None:
        return self._stats

    def on_stats_update(self, callback: object) -> None:
        self._callbacks.append(callback)

    async def start(self) -> None:
        """Start watching the stats file."""
        await self._load_stats()
        stats_file = get_stats_cache_file(self._claude_path)
        watch_dir = str(stats_file.parent)
        if Path(watch_dir).is_dir():
            self._observer = Observer()
            self._observer.daemon = True
            loop = asyncio.get_event_loop()
            handler = _StatsFileHandler(
                str(stats_file), self._on_file_changed, loop
            )
            self._observer.schedule(handler, watch_dir, recursive=False)
            self._observer.start()

    async def stop(self) -> None:
        if self._observer is not None:
            self._observer.stop()
            self._observer = None

    async def refresh(self) -> None:
        await self._load_stats()

    async def _on_file_changed(self) -> None:
        await self._load_stats()
        for cb in self._callbacks:
            try:
                await cb(self._stats)  # type: ignore[misc]
            except Exception:
                logger.exception("Error in stats update callback")

    async def _load_stats(self) -> None:
        stats_file = get_stats_cache_file(self._claude_path)
        if not stats_file.is_file():
            return
        try:
            loop = asyncio.get_event_loop()
            raw = await loop.run_in_executor(
                None, stats_file.read_text, "utf-8"
            )
            data = json.loads(raw)
            if not isinstance(data, dict):
                return

            model_usage: dict[str, ModelUsage] = {}
            raw_usage = data.get("modelUsage", {})
            if isinstance(raw_usage, dict):
                for k, v in raw_usage.items():
                    if isinstance(v, dict):
                        model_usage[k] = ModelUsage(
                            input_tokens=int(v.get("inputTokens", 0)),
                            output_tokens=int(v.get("outputTokens", 0)),
                            cache_read_input_tokens=int(v.get("cacheReadInputTokens", 0)),
                            cache_creation_input_tokens=int(v.get("cacheCreationInputTokens", 0)),
                            web_search_requests=v.get("webSearchRequests"),
                            cost_usd=v.get("costUSD"),
                        )

            daily_activity: list[DailyActivity] = []
            for entry in data.get("dailyActivity", []):
                if isinstance(entry, dict):
                    daily_activity.append(
                        DailyActivity(
                            date=str(entry.get("date", "")),
                            message_count=int(entry.get("messageCount", 0)),
                            session_count=int(entry.get("sessionCount", 0)),
                            tool_call_count=int(entry.get("toolCallCount", 0)),
                        )
                    )

            daily_model_tokens: list[DailyModelTokens] | None = None
            raw_dmt = data.get("dailyModelTokens")
            if isinstance(raw_dmt, list):
                daily_model_tokens = []
                for entry in raw_dmt:
                    if isinstance(entry, dict):
                        daily_model_tokens.append(
                            DailyModelTokens(
                                date=str(entry.get("date", "")),
                                tokens_by_model={
                                    str(k): int(v)
                                    for k, v in entry.get("tokensByModel", {}).items()
                                    if isinstance(v, (int, float))
                                },
                            )
                        )

            longest: LongestSession | None = None
            raw_longest = data.get("longestSession")
            if isinstance(raw_longest, dict):
                longest = LongestSession(
                    session_id=str(raw_longest.get("sessionId", "")),
                    duration=int(raw_longest.get("duration", 0)),
                    message_count=int(raw_longest.get("messageCount", 0)),
                    timestamp=str(raw_longest.get("timestamp", "")),
                )

            raw_hours = data.get("hourCounts")
            hour_counts: dict[str, int] | None = None
            if isinstance(raw_hours, dict):
                hour_counts = {str(k): int(v) for k, v in raw_hours.items()}

            self._stats = GlobalStatsCache(
                version=int(data.get("version", 0)),
                last_computed_date=str(data.get("lastComputedDate", "")),
                daily_activity=daily_activity,
                daily_model_tokens=daily_model_tokens,
                model_usage=model_usage,
                total_sessions=int(data.get("totalSessions", 0)),
                total_messages=int(data.get("totalMessages", 0)),
                longest_session=longest,
                first_session_date=data.get("firstSessionDate"),
                hour_counts=hour_counts,
            )
        except (json.JSONDecodeError, OSError, ValueError):
            logger.exception("Failed to parse stats cache")


class _StatsFileHandler(FileSystemEventHandler):
    def __init__(
        self, target_path: str, callback: object, loop: asyncio.AbstractEventLoop
    ) -> None:
        super().__init__()
        self._target = target_path
        self._callback = callback
        self._loop = loop

    def on_modified(self, event: FileModifiedEvent) -> None:  # type: ignore[override]
        if str(event.src_path) == self._target:
            asyncio.run_coroutine_threadsafe(self._callback(), self._loop)  # type: ignore[misc]
