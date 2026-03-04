"""Statistics models for session and usage tracking."""

from __future__ import annotations

from pydantic import BaseModel, Field, computed_field


class ModelUsage(BaseModel, frozen=True):
    """Token usage and cost for a specific model."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    web_search_requests: int = 0
    cost_usd: float = 0.0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total_tokens(self) -> int:
        """Total tokens across all categories."""
        return (
            self.input_tokens
            + self.output_tokens
            + self.cache_read_input_tokens
            + self.cache_creation_input_tokens
        )


class DailyActivity(BaseModel, frozen=True):
    """Activity counts for a single day."""

    date: str
    message_count: int = 0
    session_count: int = 0
    tool_call_count: int = 0


class DailyModelTokens(BaseModel, frozen=True):
    """Token counts by model for a single day."""

    date: str
    tokens_by_model: dict[str, int] = Field(default_factory=dict)


class LongestSession(BaseModel, frozen=True):
    """Information about the longest session."""

    session_id: str
    duration: int
    message_count: int
    timestamp: str


class GlobalStatsCache(BaseModel, frozen=True):
    """Cached global statistics."""

    version: int = 1
    last_computed_date: str = ""
    daily_activity: list[DailyActivity] = Field(default_factory=list)
    daily_model_tokens: list[DailyModelTokens] | None = None
    model_usage: dict[str, ModelUsage] = Field(default_factory=dict)
    total_sessions: int = 0
    total_messages: int = 0
    longest_session: LongestSession | None = None
    first_session_date: str | None = None
    hour_counts: dict[str, int] | None = None
