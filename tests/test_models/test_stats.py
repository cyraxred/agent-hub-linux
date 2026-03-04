"""Tests for agent_hub.models.stats module."""

from __future__ import annotations

import pytest

from agent_hub.models.stats import (
    DailyActivity,
    DailyModelTokens,
    GlobalStatsCache,
    LongestSession,
    ModelUsage,
)


# ---------- ModelUsage ----------


class TestModelUsage:
    """Tests for the ModelUsage model."""

    def test_total_tokens(self) -> None:
        usage = ModelUsage(
            input_tokens=1000,
            output_tokens=500,
            cache_read_input_tokens=200,
            cache_creation_input_tokens=100,
        )
        assert usage.total_tokens == 1800

    def test_total_tokens_zero(self) -> None:
        usage = ModelUsage()
        assert usage.total_tokens == 0

    def test_defaults(self) -> None:
        usage = ModelUsage()
        assert usage.input_tokens == 0
        assert usage.output_tokens == 0
        assert usage.cache_read_input_tokens == 0
        assert usage.cache_creation_input_tokens == 0
        assert usage.web_search_requests == 0
        assert usage.cost_usd == 0.0

    def test_with_cost(self) -> None:
        usage = ModelUsage(
            input_tokens=10000,
            output_tokens=5000,
            cost_usd=0.15,
        )
        assert usage.cost_usd == 0.15
        assert usage.total_tokens == 15000

    def test_serialization_roundtrip(self) -> None:
        usage = ModelUsage(
            input_tokens=2000,
            output_tokens=800,
            cache_read_input_tokens=300,
            cache_creation_input_tokens=50,
            web_search_requests=3,
            cost_usd=0.05,
        )
        data = usage.model_dump()
        assert data["total_tokens"] == 3150
        assert data["cost_usd"] == 0.05

        restored = ModelUsage.model_validate(data)
        assert restored.total_tokens == 3150
        assert restored.web_search_requests == 3


# ---------- DailyActivity ----------


class TestDailyActivity:
    """Tests for the DailyActivity model."""

    def test_creation(self) -> None:
        da = DailyActivity(
            date="2025-06-15",
            message_count=42,
            session_count=5,
            tool_call_count=120,
        )
        assert da.date == "2025-06-15"
        assert da.message_count == 42
        assert da.session_count == 5
        assert da.tool_call_count == 120

    def test_defaults(self) -> None:
        da = DailyActivity(date="2025-01-01")
        assert da.message_count == 0
        assert da.session_count == 0
        assert da.tool_call_count == 0

    def test_serialization(self) -> None:
        da = DailyActivity(date="2025-06-15", message_count=10)
        data = da.model_dump()
        assert data == {
            "date": "2025-06-15",
            "message_count": 10,
            "session_count": 0,
            "tool_call_count": 0,
        }
        restored = DailyActivity.model_validate(data)
        assert restored.date == "2025-06-15"


# ---------- DailyModelTokens ----------


class TestDailyModelTokens:
    """Tests for the DailyModelTokens model."""

    def test_creation(self) -> None:
        dmt = DailyModelTokens(
            date="2025-06-15",
            tokens_by_model={"claude-sonnet-4": 50000, "claude-opus-4": 10000},
        )
        assert dmt.date == "2025-06-15"
        assert dmt.tokens_by_model["claude-sonnet-4"] == 50000

    def test_defaults(self) -> None:
        dmt = DailyModelTokens(date="2025-01-01")
        assert dmt.tokens_by_model == {}


# ---------- LongestSession ----------


class TestLongestSession:
    """Tests for the LongestSession model."""

    def test_creation(self) -> None:
        ls = LongestSession(
            session_id="abc123",
            duration=3600,
            message_count=150,
            timestamp="2025-06-15T10:30:00Z",
        )
        assert ls.session_id == "abc123"
        assert ls.duration == 3600
        assert ls.message_count == 150


# ---------- GlobalStatsCache ----------


class TestGlobalStatsCache:
    """Tests for the GlobalStatsCache model."""

    def test_creation_with_all_fields(self) -> None:
        cache = GlobalStatsCache(
            version=1,
            last_computed_date="2025-06-15",
            daily_activity=[
                DailyActivity(date="2025-06-14", message_count=30, session_count=2),
                DailyActivity(date="2025-06-15", message_count=50, session_count=3),
            ],
            daily_model_tokens=[
                DailyModelTokens(
                    date="2025-06-15",
                    tokens_by_model={"claude-sonnet-4": 100000},
                ),
            ],
            model_usage={
                "claude-sonnet-4": ModelUsage(
                    input_tokens=50000, output_tokens=20000, cost_usd=0.30
                ),
            },
            total_sessions=10,
            total_messages=200,
            longest_session=LongestSession(
                session_id="best",
                duration=7200,
                message_count=300,
                timestamp="2025-06-15T08:00:00Z",
            ),
            first_session_date="2025-01-01",
            hour_counts={"0": 1, "10": 3, "15": 7},
        )
        assert cache.total_sessions == 10
        assert cache.total_messages == 200
        assert len(cache.daily_activity) == 2
        assert cache.model_usage["claude-sonnet-4"].total_tokens == 70000
        assert cache.longest_session is not None
        assert cache.longest_session.session_id == "best"
        assert cache.hour_counts is not None
        assert cache.hour_counts["10"] == 3

    def test_defaults(self) -> None:
        cache = GlobalStatsCache()
        assert cache.version == 1
        assert cache.last_computed_date == ""
        assert cache.daily_activity == []
        assert cache.daily_model_tokens is None
        assert cache.model_usage == {}
        assert cache.total_sessions == 0
        assert cache.total_messages == 0
        assert cache.longest_session is None
        assert cache.first_session_date is None
        assert cache.hour_counts is None

    def test_serialization_roundtrip(self) -> None:
        cache = GlobalStatsCache(
            total_sessions=5,
            total_messages=100,
            model_usage={
                "opus": ModelUsage(input_tokens=1000, output_tokens=500),
            },
        )
        data = cache.model_dump()
        assert data["total_sessions"] == 5

        restored = GlobalStatsCache.model_validate(data)
        assert restored.total_sessions == 5
        assert restored.model_usage["opus"].total_tokens == 1500

    def test_hour_counts_as_dict(self) -> None:
        """Validate hour_counts accepts dict[str, int] matching real stats-cache.json data."""
        raw_data = {
            "version": 1,
            "last_computed_date": "2025-06-15",
            "daily_activity": [],
            "model_usage": {},
            "total_sessions": 5,
            "total_messages": 50,
            "hour_counts": {"0": 1, "10": 3, "15": 7, "23": 2},
        }
        cache = GlobalStatsCache.model_validate(raw_data)
        assert cache.hour_counts is not None
        assert isinstance(cache.hour_counts, dict)
        assert cache.hour_counts["0"] == 1
        assert cache.hour_counts["10"] == 3
        assert cache.hour_counts["15"] == 7
        assert cache.hour_counts["23"] == 2

    def test_hour_counts_none(self) -> None:
        """hour_counts can be None."""
        cache = GlobalStatsCache(hour_counts=None)
        assert cache.hour_counts is None

    def test_hour_counts_empty_dict(self) -> None:
        """hour_counts can be an empty dict."""
        cache = GlobalStatsCache(hour_counts={})
        assert cache.hour_counts == {}

    def test_daily_model_tokens_none(self) -> None:
        """daily_model_tokens can be None."""
        cache = GlobalStatsCache(daily_model_tokens=None)
        assert cache.daily_model_tokens is None

    def test_daily_model_tokens_list(self) -> None:
        """daily_model_tokens can be a list of DailyModelTokens."""
        cache = GlobalStatsCache(
            daily_model_tokens=[
                DailyModelTokens(date="2025-06-15", tokens_by_model={"opus": 1000}),
            ],
        )
        assert cache.daily_model_tokens is not None
        assert len(cache.daily_model_tokens) == 1
        assert cache.daily_model_tokens[0].tokens_by_model["opus"] == 1000

    def test_first_session_date_none(self) -> None:
        """first_session_date can be None."""
        cache = GlobalStatsCache(first_session_date=None)
        assert cache.first_session_date is None

    def test_first_session_date_string(self) -> None:
        """first_session_date can be a string."""
        cache = GlobalStatsCache(first_session_date="2025-01-01")
        assert cache.first_session_date == "2025-01-01"

    def test_real_stats_cache_json_shape(self) -> None:
        """Test with a realistic stats-cache.json payload from disk."""
        raw = {
            "version": 1,
            "last_computed_date": "2025-06-15",
            "daily_activity": [
                {"date": "2025-06-14", "message_count": 30, "session_count": 2, "tool_call_count": 0},
            ],
            "daily_model_tokens": [
                {"date": "2025-06-15", "tokens_by_model": {"claude-sonnet-4": 100000}},
            ],
            "model_usage": {
                "claude-sonnet-4": {
                    "input_tokens": 50000,
                    "output_tokens": 20000,
                    "cache_read_input_tokens": 0,
                    "cache_creation_input_tokens": 0,
                    "web_search_requests": 0,
                    "cost_usd": 0.30,
                },
            },
            "total_sessions": 10,
            "total_messages": 200,
            "longest_session": {
                "session_id": "best",
                "duration": 7200,
                "message_count": 300,
                "timestamp": "2025-06-15T08:00:00Z",
            },
            "first_session_date": "2025-01-01",
            "hour_counts": {"0": 1, "10": 3, "15": 7},
        }
        cache = GlobalStatsCache.model_validate(raw)
        assert cache.hour_counts == {"0": 1, "10": 3, "15": 7}
        assert cache.first_session_date == "2025-01-01"
        assert cache.daily_model_tokens is not None
        assert len(cache.daily_model_tokens) == 1
