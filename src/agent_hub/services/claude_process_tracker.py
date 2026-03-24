"""ClaudeProcessTracker — maps running claude PIDs to session IDs.

Scans ``/proc`` for ``claude`` processes, correlates them with entries in
``~/.claude/agent-hub/sessions.jsonl`` (written by hooks), classifies each
into one of four categories (hub / tmux / user / third_party), and exposes
the result through public query methods and change callbacks.

Also tracks attention events (permission requests, questions) written to the
same file by hook scripts, creating and resolving notifications.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from watchdog.events import FileModifiedEvent, FileSystemEventHandler
from watchdog.observers import Observer

from agent_hub.models.process_info import (
    ClaudeProcessCategory,
    ClaudeProcessInfo,
    SessionProcessState,
    UnmatchedClaudeProcess,
)
from agent_hub.services.process_registry import ProcessRegistry

logger = logging.getLogger(__name__)

REFRESH_INTERVAL = 10.0  # seconds between periodic /proc rescans


# ---------------------------------------------------------------------------
# Internal data structures
# ---------------------------------------------------------------------------


@dataclass
class _PidSessionEntry:
    """Parsed entry from sessions.jsonl for a single PID."""

    pid: int
    session_id: str = ""
    hook_event_name: str = ""
    cwd: str = ""
    ts: float = 0


@dataclass
class _AttentionEntry:
    """An active attention event (permission request or question)."""

    session_id: str
    pid: int
    tool_name: str
    tool_use_id: str
    attention_kind: str  # "awaiting_approval" or "awaiting_question"
    ts: float = 0


# ---------------------------------------------------------------------------
# /proc helpers
# ---------------------------------------------------------------------------


def _scan_claude_pids() -> set[int]:
    """Return PIDs of all running processes whose ``comm`` is ``claude``."""
    pids: set[int] = set()
    try:
        for entry in os.listdir("/proc"):
            if not entry.isdigit():
                continue
            comm_path = f"/proc/{entry}/comm"
            try:
                with open(comm_path) as f:
                    if f.read().strip() == "claude":
                        pids.add(int(entry))
            except (OSError, ValueError):
                continue
    except OSError:
        pass
    return pids


def _pid_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def _read_proc_cwd(pid: int) -> str:
    try:
        return os.readlink(f"/proc/{pid}/cwd")
    except OSError:
        return ""


def _read_proc_ppid(pid: int) -> int | None:
    """Read the PPid from ``/proc/{pid}/status``."""
    try:
        with open(f"/proc/{pid}/status") as f:
            for line in f:
                if line.startswith("PPid:"):
                    return int(line.split(":")[1].strip())
    except (OSError, ValueError):
        pass
    return None


def _read_proc_comm(pid: int) -> str:
    try:
        with open(f"/proc/{pid}/comm") as f:
            return f.read().strip()
    except OSError:
        return ""


def _read_proc_tty_nr(pid: int) -> int:
    """Parse ``tty_nr`` from ``/proc/{pid}/stat``.

    Field layout: pid (comm) state ppid pgrp session tty_nr ...
    The comm field can contain spaces and parens so we skip past the
    closing ``)``.
    """
    try:
        with open(f"/proc/{pid}/stat") as f:
            data = f.read()
        # Everything after the last ')' gives us the remaining fields
        rest = data[data.rfind(")") + 2 :]
        fields = rest.split()
        # fields[0]=state, [1]=ppid, [2]=pgrp, [3]=session, [4]=tty_nr
        return int(fields[4])
    except (OSError, ValueError, IndexError):
        return 0


def _has_tmux_ancestor(pid: int, max_depth: int = 20) -> bool:
    """Walk the PPid chain upward and check if any ancestor is tmux."""
    current = pid
    for _ in range(max_depth):
        ppid = _read_proc_ppid(current)
        if ppid is None or ppid <= 1:
            break
        comm = _read_proc_comm(ppid)
        if comm.startswith("tmux"):
            return True
        current = ppid
    return False


# ---------------------------------------------------------------------------
# File-change handler for watchdog
# ---------------------------------------------------------------------------


class _SessionsFileHandler(FileSystemEventHandler):
    """Watchdog handler that fires a callback when sessions.jsonl changes."""

    def __init__(self, callback: Callable, loop: asyncio.AbstractEventLoop) -> None:
        super().__init__()
        self._callback = callback
        self._loop = loop

    def on_modified(self, event: FileModifiedEvent) -> None:  # type: ignore[override]
        if not event.is_directory and str(event.src_path).endswith("sessions.jsonl"):
            asyncio.run_coroutine_threadsafe(self._callback(), self._loop)


# ---------------------------------------------------------------------------
# ClaudeProcessTracker
# ---------------------------------------------------------------------------


class ClaudeProcessTracker:
    """Tracks running ``claude`` processes and maps them to session IDs."""

    def __init__(
        self,
        claude_data_path: str = "~/.claude",
        process_registry: ProcessRegistry | None = None,
    ) -> None:
        self._claude_dir = Path(claude_data_path).expanduser()
        self._agent_hub_dir = self._claude_dir / "agent-hub"
        self._sessions_file = self._agent_hub_dir / "sessions.jsonl"
        self._process_registry = process_registry

        # Internal state — process tracking
        self._pid_to_entry: dict[int, _PidSessionEntry] = {}
        self._session_to_pid: dict[str, int] = {}
        self._pid_category: dict[int, ClaudeProcessCategory] = {}
        self._unmatched_pids: set[int] = set()
        self._file_offset: int = 0

        # Internal state — attention tracking
        # Keyed by (session_id, tool_use_id) so we can resolve by either.
        self._pending_attention: dict[tuple[str, str], _AttentionEntry] = {}

        # Callbacks
        self._update_callbacks: list[Callable] = []
        self._attention_callbacks: list[Callable] = []
        self._attention_resolved_callbacks: list[Callable] = []

        # Background tasks
        self._observer: Observer | None = None
        self._refresh_task: asyncio.Task | None = None
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_process_for_session(self, session_id: str) -> ClaudeProcessInfo | None:
        """Return process info for a session, or None if no live process."""
        pid = self._session_to_pid.get(session_id)
        if pid is None:
            return None
        return self._build_process_info(pid, session_id)

    def get_all_process_states(self) -> dict[str, SessionProcessState]:
        """Return a ``SessionProcessState`` for every known session."""
        states: dict[str, SessionProcessState] = {}
        for session_id, pid in self._session_to_pid.items():
            info = self._build_process_info(pid, session_id)
            states[session_id] = SessionProcessState(
                session_id=session_id,
                process=info,
                resumable=False,
            )
        return states

    def get_unmatched_processes(self) -> list[UnmatchedClaudeProcess]:
        """Return running claude processes with no session mapping."""
        return [
            UnmatchedClaudeProcess(pid=pid, cwd=_read_proc_cwd(pid))
            for pid in sorted(self._unmatched_pids)
        ]

    def is_session_resumable(self, session_id: str) -> bool:
        """True when no live process owns this session."""
        return session_id not in self._session_to_pid

    def notify_hub_launch(self, pid: int, session_id: str) -> None:
        """Immediately register a hub-launched process."""
        entry = _PidSessionEntry(pid=pid, session_id=session_id, hook_event_name="SessionStart")
        self._pid_to_entry[pid] = entry
        self._session_to_pid[session_id] = pid
        self._pid_category[pid] = ClaudeProcessCategory.hub
        self._unmatched_pids.discard(pid)
        self._fire_callbacks()

    def notify_hub_terminate(self, pid: int) -> None:
        """Remove a hub-launched process from tracking."""
        entry = self._pid_to_entry.pop(pid, None)
        if entry and entry.session_id:
            self._session_to_pid.pop(entry.session_id, None)
        self._pid_category.pop(pid, None)
        self._unmatched_pids.discard(pid)
        self._fire_callbacks()

    def get_pending_attention(self) -> list[_AttentionEntry]:
        """Return all pending attention entries."""
        return list(self._pending_attention.values())

    def get_pending_attention_for_session(self, session_id: str) -> list[_AttentionEntry]:
        """Return pending attention entries for a specific session."""
        return [
            a for a in self._pending_attention.values()
            if a.session_id == session_id
        ]

    def on_update(self, callback: Callable) -> None:
        """Register a callback fired when process state changes."""
        self._update_callbacks.append(callback)

    def on_attention(self, callback: Callable) -> None:
        """Register a callback fired when a new attention event arrives.

        Callback signature: ``async def cb(entry: _AttentionEntry) -> None``
        """
        self._attention_callbacks.append(callback)

    def on_attention_resolved(self, callback: Callable) -> None:
        """Register a callback fired when an attention event is resolved.

        Callback signature: ``async def cb(session_id: str, tool_use_id: str) -> None``
        """
        self._attention_resolved_callbacks.append(callback)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start tracking: initial scan, file watcher, periodic refresh."""
        async with self._lock:
            # Ensure agent-hub directory exists
            self._agent_hub_dir.mkdir(parents=True, exist_ok=True)

            # 1. Scan /proc for running claude pids
            running_pids = await asyncio.get_event_loop().run_in_executor(
                None, _scan_claude_pids
            )

            # 2. Parse sessions.jsonl fully
            self._parse_sessions_file_full(running_pids)

            # 3. Classify each mapped pid
            for pid in list(self._pid_to_entry):
                if pid not in self._pid_category:
                    self._pid_category[pid] = self._classify_pid(pid)

            # 4. Start watchdog on ~/.claude/agent-hub/ for sessions.jsonl changes
            if self._agent_hub_dir.is_dir():
                loop = asyncio.get_event_loop()
                handler = _SessionsFileHandler(self._on_sessions_file_changed, loop)
                self._observer = Observer()
                self._observer.daemon = True
                self._observer.schedule(handler, str(self._agent_hub_dir), recursive=False)
                self._observer.start()

            # 5. Start periodic refresh
            self._refresh_task = asyncio.create_task(self._periodic_refresh())

        logger.info(
            "ClaudeProcessTracker started: %d mapped, %d unmatched, %d pending attention",
            len(self._session_to_pid),
            len(self._unmatched_pids),
            len(self._pending_attention),
        )

    async def stop(self) -> None:
        """Stop all background work."""
        if self._observer is not None:
            self._observer.stop()
            self._observer = None
        if self._refresh_task is not None:
            self._refresh_task.cancel()
            try:
                await self._refresh_task
            except asyncio.CancelledError:
                pass
            self._refresh_task = None
        logger.info("ClaudeProcessTracker stopped")

    # ------------------------------------------------------------------
    # Internal: file parsing
    # ------------------------------------------------------------------

    def _parse_sessions_file_full(self, running_pids: set[int]) -> None:
        """Parse the entire sessions.jsonl; keep only entries for running PIDs."""
        if not self._sessions_file.is_file():
            self._unmatched_pids = set(running_pids)
            self._file_offset = 0
            return

        last_entry: dict[int, _PidSessionEntry] = {}
        all_attention: list[_AttentionEntry] = []
        try:
            with open(self._sessions_file, "rb") as f:
                for raw_line in f:
                    self._parse_line(raw_line, last_entry, all_attention)
                self._file_offset = f.tell()
        except OSError:
            logger.exception("Failed to read %s", self._sessions_file)
            self._unmatched_pids = set(running_pids)
            return

        # Keep only entries for PIDs that are actually running
        for pid in running_pids:
            entry = last_entry.get(pid)
            if entry is None or entry.hook_event_name == "SessionEnd" or not entry.session_id:
                self._unmatched_pids.add(pid)
            else:
                self._pid_to_entry[pid] = entry
                self._session_to_pid[entry.session_id] = pid

        # Determine the most recent SessionStart timestamp per session.
        # Only attention entries *after* the last SessionStart are valid —
        # earlier ones belong to a previous session incarnation.
        session_start_ts: dict[str, float] = {}
        for entry in last_entry.values():
            if entry.hook_event_name == "SessionStart" and entry.session_id:
                prev = session_start_ts.get(entry.session_id, 0)
                if entry.ts > prev:
                    session_start_ts[entry.session_id] = entry.ts

        # Restore pending attention for live sessions only, filtering out
        # entries that predate the most recent SessionStart.
        live_sessions = set(self._session_to_pid.keys())
        for att in all_attention:
            if att.session_id not in live_sessions:
                continue
            start_ts = session_start_ts.get(att.session_id, 0)
            if att.ts >= start_ts:
                self._pending_attention[(att.session_id, att.tool_use_id)] = att

    def _parse_incremental(self) -> tuple[bool, list[_AttentionEntry], list[tuple[str, str]]]:
        """Read new bytes since last offset.

        Returns ``(process_changed, new_attention_list, resolved_list)``
        where ``resolved_list`` contains ``(session_id, tool_use_id)`` pairs
        for attention events that were resolved by a SessionEnd or SessionStart.
        """
        if not self._sessions_file.is_file():
            return False, [], []
        try:
            file_size = self._sessions_file.stat().st_size
        except OSError:
            return False, [], []
        if file_size <= self._file_offset:
            return False, [], []

        try:
            with open(self._sessions_file, "rb") as f:
                f.seek(self._file_offset)
                new_data = f.read()
                self._file_offset = f.tell()
        except OSError:
            return False, [], []

        process_changed = False
        new_attention: list[_AttentionEntry] = []
        resolved: list[tuple[str, str]] = []

        temp_entries: dict[int, _PidSessionEntry] = {}
        raw_attention: list[_AttentionEntry] = []
        for raw_line in new_data.splitlines():
            self._parse_line(raw_line, temp_entries, raw_attention)

        # Process session lifecycle entries
        for pid, entry in temp_entries.items():
            if not _pid_is_alive(pid):
                continue

            if entry.hook_event_name == "SessionEnd" or not entry.session_id:
                old = self._pid_to_entry.pop(pid, None)
                if old and old.session_id:
                    self._session_to_pid.pop(old.session_id, None)
                    # Resolve any pending attention for this session
                    resolved.extend(self._resolve_attention_for_session(old.session_id))
                self._unmatched_pids.add(pid)
                process_changed = True
            elif entry.hook_event_name == "SessionStart":
                # New SessionStart invalidates any pending attention from a
                # previous incarnation of this session (Claude restarted).
                resolved.extend(self._resolve_attention_for_session(entry.session_id))
                self._pid_to_entry[pid] = entry
                self._session_to_pid[entry.session_id] = pid
                self._unmatched_pids.discard(pid)
                if pid not in self._pid_category:
                    self._pid_category[pid] = self._classify_pid(pid)
                process_changed = True

        # Process attention entries
        for att in raw_attention:
            key = (att.session_id, att.tool_use_id)
            self._pending_attention[key] = att
            new_attention.append(att)

        return process_changed, new_attention, resolved

    def _resolve_attention_for_session(self, session_id: str) -> list[tuple[str, str]]:
        """Remove all pending attention for a session. Returns resolved keys."""
        to_remove = [
            k for k in self._pending_attention if k[0] == session_id
        ]
        for k in to_remove:
            del self._pending_attention[k]
        return to_remove

    def resolve_attention(self, session_id: str, tool_use_id: str) -> bool:
        """Resolve a specific attention entry (called by transcript watcher).

        Returns True if any entry was removed.
        """
        resolved = False
        key = (session_id, tool_use_id)
        if key in self._pending_attention:
            del self._pending_attention[key]
            resolved = True

        # Also clear entries with empty tool_use_id for this session — these
        # come from hooks that don't provide tool_use_id. Any tool_result
        # for the session means the agent moved past the attention state.
        empty_key = (session_id, "")
        if empty_key in self._pending_attention:
            del self._pending_attention[empty_key]
            resolved = True

        if resolved:
            self._fire_attention_resolved_callbacks(session_id, tool_use_id)
        return resolved

    @staticmethod
    def _parse_line(
        raw_line: bytes,
        session_dest: dict[int, _PidSessionEntry],
        attention_dest: list[_AttentionEntry],
    ) -> None:
        """Parse a single JSONL line.

        Session lifecycle entries go into *session_dest* (keyed by PID,
        last write wins).  Attention entries are appended to *attention_dest*.
        """
        raw_line = raw_line.strip()
        if not raw_line:
            return
        try:
            obj = json.loads(raw_line)
        except (json.JSONDecodeError, ValueError):
            return
        if not isinstance(obj, dict):
            return

        pid = obj.get("pid")
        if not isinstance(pid, int):
            return

        event = str(obj.get("event", "") or "")
        hook_event_name = str(obj.get("hook_event_name", "") or "")

        if event == "attention":
            # Attention event from PermissionRequest or PreToolUse[AskUserQuestion]
            session_id = str(obj.get("session_id", "") or "")
            tool_name = str(obj.get("tool_name", "") or "")
            tool_use_id = str(obj.get("tool_use_id", "") or "")
            if not session_id:
                return

            is_question = hook_event_name == "PreToolUse" and tool_name.lower() in (
                "askuserquestion", "ask_user_question",
            )
            attention_kind = "awaiting_question" if is_question else "awaiting_approval"

            attention_dest.append(_AttentionEntry(
                session_id=session_id,
                pid=pid,
                tool_name=tool_name,
                tool_use_id=tool_use_id,
                attention_kind=attention_kind,
                ts=float(obj.get("ts", 0) or 0),
            ))
        else:
            # Session lifecycle entry (SessionStart / SessionEnd)
            session_dest[pid] = _PidSessionEntry(
                pid=pid,
                session_id=str(obj.get("session_id", "") or ""),
                hook_event_name=hook_event_name,
                cwd=str(obj.get("cwd", "") or ""),
                ts=float(obj.get("ts", 0) or 0),
            )

    # ------------------------------------------------------------------
    # Internal: classification
    # ------------------------------------------------------------------

    def _classify_pid(self, pid: int) -> ClaudeProcessCategory:
        """Classify a claude PID into one of the four categories."""
        # 1. Hub-spawned?
        if self._process_registry is not None:
            for key in self._process_registry.keys():
                proc = self._process_registry.get(key)
                if proc is not None and proc.pid == pid:
                    return ClaudeProcessCategory.hub

        # 2. Tmux descendant?
        if _has_tmux_ancestor(pid):
            return ClaudeProcessCategory.tmux

        # 3. Has a controlling TTY?
        tty_nr = _read_proc_tty_nr(pid)
        if tty_nr != 0:
            return ClaudeProcessCategory.user

        # 4. Fallback
        return ClaudeProcessCategory.third_party

    # ------------------------------------------------------------------
    # Internal: monitoring flags
    # ------------------------------------------------------------------

    def _build_process_info(self, pid: int, session_id: str) -> ClaudeProcessInfo:
        category = self._pid_category.get(pid, ClaudeProcessCategory.third_party)
        entry = self._pid_to_entry.get(pid)

        if category == ClaudeProcessCategory.hub:
            monitored = True
            terminal_connected = True
        elif category == ClaudeProcessCategory.tmux:
            monitored = False
            terminal_connected = False
        else:
            # user / third_party — monitored if we have a file watcher
            monitored = True
            terminal_connected = False

        return ClaudeProcessInfo(
            pid=pid,
            session_id=session_id,
            category=category,
            monitored=monitored,
            terminal_connected=terminal_connected,
            cwd=entry.cwd if entry else _read_proc_cwd(pid),
            started_at=entry.ts if entry else 0,
        )

    # ------------------------------------------------------------------
    # Internal: callbacks
    # ------------------------------------------------------------------

    def _fire_callbacks(self) -> None:
        """Schedule registered process-update callbacks on the event loop."""
        for cb in self._update_callbacks:
            try:
                loop = asyncio.get_event_loop()
                asyncio.run_coroutine_threadsafe(cb(), loop)
            except RuntimeError:
                pass

    def _fire_attention_callbacks(self, entry: _AttentionEntry) -> None:
        """Schedule attention callbacks for a new attention event."""
        for cb in self._attention_callbacks:
            try:
                loop = asyncio.get_event_loop()
                asyncio.run_coroutine_threadsafe(cb(entry), loop)
            except RuntimeError:
                pass

    def _fire_attention_resolved_callbacks(self, session_id: str, tool_use_id: str) -> None:
        """Schedule callbacks for a resolved attention event."""
        for cb in self._attention_resolved_callbacks:
            try:
                loop = asyncio.get_event_loop()
                asyncio.run_coroutine_threadsafe(cb(session_id, tool_use_id), loop)
            except RuntimeError:
                pass

    # ------------------------------------------------------------------
    # Internal: file watcher callback
    # ------------------------------------------------------------------

    async def _on_sessions_file_changed(self) -> None:
        """Called by watchdog when sessions.jsonl is modified."""
        async with self._lock:
            process_changed, new_attention, resolved = self._parse_incremental()

            if process_changed:
                self._fire_callbacks()

            for att in new_attention:
                self._fire_attention_callbacks(att)

            for session_id, tool_use_id in resolved:
                self._fire_attention_resolved_callbacks(session_id, tool_use_id)

    # ------------------------------------------------------------------
    # Internal: periodic refresh
    # ------------------------------------------------------------------

    async def _periodic_refresh(self) -> None:
        """Periodically recheck tracked PIDs and scan for new ones."""
        try:
            while True:
                await asyncio.sleep(REFRESH_INTERVAL)
                await self._do_refresh()
        except asyncio.CancelledError:
            pass

    async def _do_refresh(self) -> None:
        async with self._lock:
            changed = False
            all_resolved: list[tuple[str, str]] = []

            # 1. Check alive status of all tracked PIDs
            dead_pids: list[int] = []
            for pid in list(self._pid_to_entry):
                if not _pid_is_alive(pid):
                    dead_pids.append(pid)
            for pid in dead_pids:
                entry = self._pid_to_entry.pop(pid)
                if entry.session_id:
                    self._session_to_pid.pop(entry.session_id, None)
                    # Resolve attention for dead sessions
                    all_resolved.extend(
                        self._resolve_attention_for_session(entry.session_id)
                    )
                self._pid_category.pop(pid, None)
                changed = True

            # Remove dead unmatched pids too
            dead_unmatched = [p for p in self._unmatched_pids if not _pid_is_alive(p)]
            for pid in dead_unmatched:
                self._unmatched_pids.discard(pid)
                changed = True

            # 2. Rescan /proc for new claude processes
            current_pids = await asyncio.get_event_loop().run_in_executor(
                None, _scan_claude_pids
            )
            known_pids = set(self._pid_to_entry.keys()) | self._unmatched_pids
            new_pids = current_pids - known_pids
            if new_pids:
                # Try incremental parse to see if they have entries
                _changed, _att, _resolved = self._parse_incremental()
                all_resolved.extend(_resolved)
                for pid in new_pids:
                    if pid not in self._pid_to_entry:
                        self._unmatched_pids.add(pid)
                    if pid not in self._pid_category and pid in self._pid_to_entry:
                        self._pid_category[pid] = self._classify_pid(pid)
                changed = True

            # 3. Reclassify if process registry changed
            if self._process_registry is not None:
                hub_pids = set()
                for key in self._process_registry.keys():
                    proc = self._process_registry.get(key)
                    if proc is not None:
                        hub_pids.add(proc.pid)
                for pid in list(self._pid_to_entry):
                    old_cat = self._pid_category.get(pid)
                    if pid in hub_pids and old_cat != ClaudeProcessCategory.hub:
                        self._pid_category[pid] = ClaudeProcessCategory.hub
                        changed = True
                    elif pid not in hub_pids and old_cat == ClaudeProcessCategory.hub:
                        self._pid_category[pid] = self._classify_pid(pid)
                        changed = True

            if changed:
                self._fire_callbacks()

            for session_id, tool_use_id in all_resolved:
                self._fire_attention_resolved_callbacks(session_id, tool_use_id)
