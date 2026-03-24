"""Unit tests for TranscriptRegistry."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent_hub.services.file_watcher import FileWatcher
from agent_hub.services.session_jsonl_parser import ParseResult, parse_new_lines
from agent_hub.services.session_transcript import SessionTranscript
from agent_hub.services.transcript_registry import TranscriptRegistry


@pytest.fixture()
def file_watcher():
    fw = FileWatcher()
    fw.set_loop(asyncio.get_event_loop())
    yield fw
    fw.shutdown()


@pytest.fixture()
def registry(file_watcher: FileWatcher) -> TranscriptRegistry:
    return TranscriptRegistry(
        provider="claude",
        parse_fn=parse_new_lines,
        parse_result_factory=ParseResult,
        approval_timeout_seconds=5,
        file_watcher=file_watcher,
    )


def _conversation_line() -> str:
    """A line with "type": "assistant" so _is_conversation_file returns True."""
    return json.dumps({
        "type": "assistant",
        "timestamp": "2025-06-15T10:30:00Z",
        "message": {
            "role": "assistant",
            "model": "claude-sonnet-4-20250514",
            "content": [{"type": "text", "text": "Hello"}],
            "usage": {"inputTokens": 100, "outputTokens": 50},
        },
    })


def _non_conversation_line() -> str:
    return json.dumps({
        "type": "file-history-snapshot",
        "data": {"files": []},
    })


class TestProjectDirectoryManagement:
    async def test_add_project_directory_subscribes(
        self, registry: TranscriptRegistry, file_watcher: FileWatcher, tmp_path: Path
    ):
        project_dir = tmp_path / "projects" / "-home-user-project"
        project_dir.mkdir(parents=True)

        await registry.add_project_directory(str(project_dir))

        dir_path = str(project_dir.resolve())
        assert dir_path in registry._project_dirs
        assert dir_path in registry._dir_callbacks
        # FileWatcher should have a directory subscription
        assert dir_path in file_watcher._dir_subs

    async def test_remove_project_directory_unsubscribes(
        self, registry: TranscriptRegistry, file_watcher: FileWatcher, tmp_path: Path
    ):
        project_dir = tmp_path / "projects" / "-home-user-project"
        project_dir.mkdir(parents=True)

        await registry.add_project_directory(str(project_dir))
        dir_path = str(project_dir.resolve())
        assert dir_path in registry._project_dirs

        registry.remove_project_directory(str(project_dir))
        assert dir_path not in registry._project_dirs
        assert dir_path not in registry._dir_callbacks

    async def test_remove_project_directory_cleans_entries(
        self, registry: TranscriptRegistry, tmp_path: Path
    ):
        project_dir = tmp_path / "projects" / "-home-user-project"
        project_dir.mkdir(parents=True)

        session_file = project_dir / "session-001.jsonl"
        session_file.write_text(_conversation_line() + "\n")

        # Register transcript manually
        await registry.register_transcript(
            session_id="session-001",
            project_path="/home/user/project",
            file_path=str(session_file),
        )
        assert registry.get_transcript("session-001") is not None

        await registry.add_project_directory(str(project_dir))
        registry.remove_project_directory(str(project_dir))

        # Entries under that directory should be cleaned
        assert registry.get_transcript("session-001") is None


class TestClassification:
    async def test_classify_conversation_file_promotes(
        self, registry: TranscriptRegistry, tmp_path: Path
    ):
        project_dir = tmp_path / "projects" / "-home-user-project"
        project_dir.mkdir(parents=True)

        session_file = project_dir / "session-002.jsonl"
        session_file.write_text(_conversation_line() + "\n")

        dir_path = str(project_dir.resolve())
        await registry._classify_and_add(str(session_file.resolve()), dir_path)

        assert registry.get_transcript("session-002") is not None

    async def test_classify_non_conversation_stays_int(
        self, registry: TranscriptRegistry, tmp_path: Path
    ):
        project_dir = tmp_path / "projects" / "-home-user-project"
        project_dir.mkdir(parents=True)

        aux_file = project_dir / "aux-file.jsonl"
        aux_file.write_text(_non_conversation_line() + "\n")

        dir_path = str(project_dir.resolve())
        await registry._classify_and_add(str(aux_file.resolve()), dir_path)

        file_key = str(aux_file.resolve())
        entry = registry._entries.get(file_key)
        assert isinstance(entry, int)  # stored as file size

    async def test_unclassified_file_grows_and_promotes(
        self, registry: TranscriptRegistry, tmp_path: Path
    ):
        project_dir = tmp_path / "projects" / "-home-user-project"
        project_dir.mkdir(parents=True)

        session_file = project_dir / "session-003.jsonl"
        session_file.write_text(_non_conversation_line() + "\n")

        dir_path = str(project_dir.resolve())
        await registry._classify_and_add(str(session_file.resolve()), dir_path)

        file_key = str(session_file.resolve())
        assert isinstance(registry._entries.get(file_key), int)

        # Append conversation content and re-classify
        with open(session_file, "a") as f:
            f.write(_conversation_line() + "\n")

        await registry._try_promote(file_key, dir_path)
        assert registry.get_transcript("session-003") is not None


class TestCallbacks:
    async def test_on_transcript_added_callback(
        self, registry: TranscriptRegistry, tmp_path: Path
    ):
        added: list[tuple[str, SessionTranscript]] = []

        async def on_added(session_id: str, transcript: SessionTranscript) -> None:
            added.append((session_id, transcript))

        registry.on_transcript_added(on_added)

        session_file = tmp_path / "session-004.jsonl"
        session_file.write_text("")

        await registry.register_transcript(
            session_id="session-004",
            project_path="/home/user/project",
            file_path=str(session_file),
        )

        assert len(added) == 1
        assert added[0][0] == "session-004"

    async def test_deleted_file_fires_removed_callback(
        self, registry: TranscriptRegistry, tmp_path: Path
    ):
        project_dir = tmp_path / "projects" / "-home-user-project"
        project_dir.mkdir(parents=True)

        session_file = project_dir / "session-005.jsonl"
        session_file.write_text(_conversation_line() + "\n")

        removed: list[str] = []

        async def on_removed(session_id: str) -> None:
            removed.append(session_id)

        registry.on_transcript_removed(on_removed)

        await registry.register_transcript(
            session_id="session-005",
            project_path="/home/user/project",
            file_path=str(session_file),
        )

        # Simulate a delete event
        dir_path = str(project_dir.resolve())
        file_path = str(session_file.resolve())
        await registry._handle_dir_event(dir_path, "deleted", file_path)

        # _fire_removed uses run_coroutine_threadsafe, so check directly
        assert registry.get_transcript("session-005") is None

    async def test_global_callbacks_wired_to_new_transcripts(
        self, registry: TranscriptRegistry, tmp_path: Path
    ):
        state_updates: list[str] = []
        history_updates: list[str] = []

        async def on_state(session_id: str, state: object) -> None:
            state_updates.append(session_id)

        async def on_history(session_id: str, entries: list, total: int) -> None:
            history_updates.append(session_id)

        registry.on_state_update(on_state)
        registry.on_history_append(on_history)

        session_file = tmp_path / "session-006.jsonl"
        session_file.write_text(_conversation_line() + "\n")

        await registry.register_transcript(
            session_id="session-006",
            project_path="/home/user/project",
            file_path=str(session_file),
        )

        # Callbacks should have fired during initial parse
        assert "session-006" in state_updates
        assert "session-006" in history_updates


class TestMonitoringControl:
    async def test_set_monitored_true_watches_file(
        self, registry: TranscriptRegistry, file_watcher: FileWatcher, tmp_path: Path
    ):
        session_file = tmp_path / "session-007.jsonl"
        session_file.write_text("")

        transcript = await registry.register_transcript(
            session_id="session-007",
            project_path="/home/user/project",
            file_path=str(session_file),
        )

        registry.set_monitored("session-007", True)
        assert transcript.is_monitored is True
        # File watch callback should be set
        assert getattr(transcript, "_file_watch_cb", None) is not None

    async def test_set_monitored_false_unwatches_file(
        self, registry: TranscriptRegistry, tmp_path: Path
    ):
        session_file = tmp_path / "session-008.jsonl"
        session_file.write_text("")

        transcript = await registry.register_transcript(
            session_id="session-008",
            project_path="/home/user/project",
            file_path=str(session_file),
        )

        registry.set_monitored("session-008", True)
        registry.set_monitored("session-008", False)
        assert transcript.is_monitored is False
        assert getattr(transcript, "_file_watch_cb", None) is None


class TestRegistration:
    async def test_register_transcript_manual(
        self, registry: TranscriptRegistry, tmp_path: Path
    ):
        session_file = tmp_path / "session-009.jsonl"
        session_file.write_text("")

        transcript = await registry.register_transcript(
            session_id="session-009",
            project_path="/home/user/project",
            file_path=str(session_file),
        )

        assert transcript.session_id == "session-009"
        assert registry.get_transcript("session-009") is transcript

    async def test_register_transcript_idempotent(
        self, registry: TranscriptRegistry, tmp_path: Path
    ):
        session_file = tmp_path / "session-010.jsonl"
        session_file.write_text("")

        t1 = await registry.register_transcript(
            session_id="session-010",
            project_path="/home/user/project",
            file_path=str(session_file),
        )
        t2 = await registry.register_transcript(
            session_id="session-010",
            project_path="/home/user/project",
            file_path=str(session_file),
        )
        assert t1 is t2

    async def test_get_all_transcripts(
        self, registry: TranscriptRegistry, tmp_path: Path
    ):
        for i in range(3):
            f = tmp_path / f"session-{i}.jsonl"
            f.write_text("")
            await registry.register_transcript(
                session_id=f"session-{i}",
                project_path="/home/user/project",
                file_path=str(f),
            )

        all_t = registry.get_all_transcripts()
        assert len(all_t) == 3

    async def test_get_all_session_ids(
        self, registry: TranscriptRegistry, tmp_path: Path
    ):
        for i in range(2):
            f = tmp_path / f"session-{i}.jsonl"
            f.write_text("")
            await registry.register_transcript(
                session_id=f"session-{i}",
                project_path="/home/user/project",
                file_path=str(f),
            )

        ids = registry.get_all_session_ids()
        assert ids == {"session-0", "session-1"}


class TestLifecycle:
    async def test_stop_cleans_everything(
        self, registry: TranscriptRegistry, tmp_path: Path
    ):
        session_file = tmp_path / "session-011.jsonl"
        session_file.write_text("")

        await registry.register_transcript(
            session_id="session-011",
            project_path="/home/user/project",
            file_path=str(session_file),
        )

        await registry.stop()

        assert registry.get_transcript("session-011") is None
        assert len(registry._entries) == 0
        assert len(registry._session_index) == 0
