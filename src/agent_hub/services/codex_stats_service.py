"""Codex global stats service."""

from __future__ import annotations

import logging
from pathlib import Path

from agent_hub.models.stats import GlobalStatsCache, ModelUsage
from agent_hub.services.codex_jsonl_parser import parse_for_global_stats

logger = logging.getLogger(__name__)


class CodexGlobalStatsService:
    """Computes global stats for Codex by scanning session files."""

    def __init__(self, codex_data_path: str = "~/.codex") -> None:
        self._codex_path = str(Path(codex_data_path).expanduser())
        self._stats: GlobalStatsCache | None = None

    @property
    def stats(self) -> GlobalStatsCache | None:
        return self._stats

    async def refresh(self) -> None:
        """Scan all Codex sessions and compute aggregate stats."""
        sessions_dir = Path(self._codex_path) / "sessions"
        if not sessions_dir.is_dir():
            return

        total_messages = 0
        total_sessions = 0
        model_usage: dict[str, ModelUsage] = {}

        for date_dir in sorted(sessions_dir.iterdir()):
            if not date_dir.is_dir():
                continue
            for sf in date_dir.glob("*.jsonl"):
                total_sessions += 1
                result = parse_for_global_stats(str(sf))
                total_messages += result.message_count

                model_key = result.model or "unknown"
                existing = model_usage.get(model_key)
                if existing:
                    model_usage[model_key] = ModelUsage(
                        input_tokens=existing.input_tokens + result.total_input_tokens,
                        output_tokens=existing.output_tokens + result.total_output_tokens,
                        cache_read_input_tokens=existing.cache_read_input_tokens + result.cache_read_tokens,
                        cache_creation_input_tokens=existing.cache_creation_input_tokens,
                    )
                else:
                    model_usage[model_key] = ModelUsage(
                        input_tokens=result.total_input_tokens,
                        output_tokens=result.total_output_tokens,
                        cache_read_input_tokens=result.cache_read_tokens,
                        cache_creation_input_tokens=0,
                    )

        self._stats = GlobalStatsCache(
            version=1,
            last_computed_date="",
            daily_activity=[],
            model_usage=model_usage,
            total_sessions=total_sessions,
            total_messages=total_messages,
        )
