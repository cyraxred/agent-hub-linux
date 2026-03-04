"""Tests for agent_hub.services.session_parse_cache module."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agent_hub.services.session_parse_cache import SessionParseCache
from agent_hub.services.session_jsonl_parser import ParseResult, PlanEntry, MermaidDiagram


def _write_session_file(path: Path, entries: list[dict]) -> None:
    """Write a list of JSONL entries to a file."""
    with open(path, "w") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")


def _make_user_message(ts: str = "2025-06-15T10:00:00Z") -> dict:
    return {
        "type": "message",
        "timestamp": ts,
        "message": {
            "role": "user",
            "content": [{"type": "text", "text": "Hello"}],
        },
    }


def _make_assistant_message(ts: str = "2025-06-15T10:01:00Z") -> dict:
    return {
        "type": "message",
        "timestamp": ts,
        "message": {
            "role": "assistant",
            "model": "claude-opus-4-6",
            "usage": {
                "input_tokens": 100,
                "output_tokens": 50,
            },
            "content": [{"type": "text", "text": "Hi there!"}],
        },
    }


class TestSessionParseCache:
    """Tests for the SessionParseCache class."""

    def test_cache_miss_triggers_full_parse(self, tmp_path: Path) -> None:
        cache = SessionParseCache(max_size=10, approval_timeout_seconds=0)
        session_file = tmp_path / "session.jsonl"
        _write_session_file(session_file, [_make_user_message(), _make_assistant_message()])

        result = cache.get("s1", str(session_file), "claude")
        assert result is not None
        assert result.message_count == 1
        assert result.model == "claude-opus-4-6"
        assert cache.size == 1

    def test_cache_hit_same_file_size(self, tmp_path: Path) -> None:
        cache = SessionParseCache(max_size=10, approval_timeout_seconds=0)
        session_file = tmp_path / "session.jsonl"
        _write_session_file(session_file, [_make_user_message(), _make_assistant_message()])

        r1 = cache.get("s1", str(session_file), "claude")
        r2 = cache.get("s1", str(session_file), "claude")
        # Same object returned (cache hit)
        assert r1 is r2

    def test_cache_invalidation_on_file_growth(self, tmp_path: Path) -> None:
        cache = SessionParseCache(max_size=10, approval_timeout_seconds=0)
        session_file = tmp_path / "session.jsonl"
        _write_session_file(session_file, [_make_user_message()])

        r1 = cache.get("s1", str(session_file), "claude")
        assert r1 is not None
        assert r1.message_count == 1

        # Append more data
        with open(session_file, "a") as f:
            f.write(json.dumps(_make_user_message("2025-06-15T10:05:00Z")) + "\n")

        r2 = cache.get("s1", str(session_file), "claude")
        assert r2 is not None
        # Re-parsed: new result
        assert r2 is not r1
        assert r2.message_count == 2

    def test_lru_eviction(self, tmp_path: Path) -> None:
        cache = SessionParseCache(max_size=3, approval_timeout_seconds=0)

        for i in range(5):
            sf = tmp_path / f"session_{i}.jsonl"
            _write_session_file(sf, [_make_user_message()])
            cache.get(f"s{i}", str(sf), "claude")

        # Only last 3 should remain
        assert cache.size == 3

    def test_put_write_through(self, tmp_path: Path) -> None:
        cache = SessionParseCache(max_size=10, approval_timeout_seconds=0)
        session_file = tmp_path / "session.jsonl"
        _write_session_file(session_file, [_make_user_message()])

        # Manually put a ParseResult
        pr = ParseResult(message_count=42, model="test-model")
        file_size = session_file.stat().st_size
        cache.put("s1", str(session_file), file_size, pr, "claude")

        # Get should return the put result (same file size)
        result = cache.get("s1", str(session_file), "claude")
        assert result is pr
        assert result.message_count == 42

    def test_invalidate_removes_entry(self, tmp_path: Path) -> None:
        cache = SessionParseCache(max_size=10, approval_timeout_seconds=0)
        session_file = tmp_path / "session.jsonl"
        _write_session_file(session_file, [_make_user_message()])

        cache.get("s1", str(session_file), "claude")
        assert cache.size == 1

        cache.invalidate("s1", "claude")
        assert cache.size == 0

    def test_clear(self, tmp_path: Path) -> None:
        cache = SessionParseCache(max_size=10, approval_timeout_seconds=0)
        for i in range(3):
            sf = tmp_path / f"s{i}.jsonl"
            _write_session_file(sf, [_make_user_message()])
            cache.get(f"s{i}", str(sf), "claude")

        assert cache.size == 3
        cache.clear()
        assert cache.size == 0

    def test_nonexistent_file_returns_none(self) -> None:
        cache = SessionParseCache(max_size=10)
        result = cache.get("s1", "/nonexistent/file.jsonl", "claude")
        assert result is None
        assert cache.size == 0

    def test_provider_isolation(self, tmp_path: Path) -> None:
        """Same session_id with different providers are separate cache entries."""
        cache = SessionParseCache(max_size=10, approval_timeout_seconds=0)
        sf = tmp_path / "session.jsonl"
        _write_session_file(sf, [_make_user_message()])

        r_claude = cache.get("s1", str(sf), "claude")
        r_codex = cache.get("s1", str(sf), "codex")
        assert r_claude is not None
        assert r_codex is not None
        assert cache.size == 2

    def test_thread_safety(self, tmp_path: Path) -> None:
        """Concurrent reads from multiple threads don't crash."""
        cache = SessionParseCache(max_size=100, approval_timeout_seconds=0)
        session_file = tmp_path / "session.jsonl"
        _write_session_file(session_file, [_make_user_message(), _make_assistant_message()])

        errors: list[Exception] = []

        def reader(tid: int) -> None:
            try:
                for _ in range(20):
                    r = cache.get(f"s{tid % 5}", str(session_file), "claude")
                    assert r is not None
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=reader, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
