"""Session routes for listing, monitoring, and querying sessions."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from agent_hub.models.monitor_state import (
    MermaidDiagramInfo,
    PlanInfo,
    SessionMonitorState,
)
from agent_hub.models.session import CLISession, SelectedRepository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


# ---------------------------------------------------------------------------
# Response / request schemas
# ---------------------------------------------------------------------------


class SessionListResponse(BaseModel):
    """Response containing all sessions across all repositories."""

    sessions: list[CLISession]
    total: int


class SessionDetailResponse(BaseModel):
    """Detailed session info, including the repository it belongs to."""

    session: CLISession
    repository_path: str
    provider: str


class MonitorStartRequest(BaseModel):
    """Request body for starting session monitoring."""

    project_path: str
    session_file_path: str | None = None
    provider: Literal["claude", "codex"] = "claude"


class MonitorStateResponse(BaseModel):
    """Response containing the current monitor state."""

    session_id: str
    state: SessionMonitorState | None = None
    monitoring: bool = False


class RefreshResponse(BaseModel):
    """Generic refresh response."""

    success: bool = True
    message: str = ""


class CreatePendingSessionRequest(BaseModel):
    """Request body for creating a pre-seeded pending session."""

    project_path: str
    prompt: str = ""


class CreatePendingSessionResponse(BaseModel):
    """Response after creating a pending session file."""

    session_id: str
    session_file_path: str


class SessionNameRequest(BaseModel):
    """Request body for setting a custom session name."""

    name: str | None = None


class SessionNameResponse(BaseModel):
    """Response after setting a session name."""

    session_id: str
    name: str | None = None


class AllSessionNamesResponse(BaseModel):
    """Response containing all custom session names."""

    names: dict[str, str]


class HistoryEntry(BaseModel):
    """A single raw JSONL entry from the session file."""

    line: int
    type: str
    data: dict[str, Any]


class SessionHistoryResponse(BaseModel):
    """Paginated session history."""

    session_id: str
    entries: list[HistoryEntry]
    total_lines: int
    offset: int
    has_more: bool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_provider(request: Request):
    """Retrieve the AgentHubProvider from app state."""
    return request.app.state.provider


def _find_session_across_providers(
    provider,
    session_id: str,
) -> tuple[CLISession | None, str, str]:
    """Search for a session across both Claude and Codex monitors.

    Returns (session, repository_path, provider_name).
    """
    # Search Claude repositories
    for repo in provider.claude_monitor.repositories:
        for wt in repo.worktrees:
            for sess in wt.sessions:
                if sess.id == session_id:
                    return sess, repo.path, "claude"

    # Search Codex repositories
    for repo in provider.codex_monitor.repositories:
        for wt in repo.worktrees:
            for sess in wt.sessions:
                if sess.id == session_id:
                    return sess, repo.path, "codex"

    return None, "", ""


def _collect_all_sessions(
    provider,
) -> list[CLISession]:
    """Collect every session from every repository across both providers."""
    sessions: list[CLISession] = []
    for repo in provider.claude_monitor.repositories:
        for wt in repo.worktrees:
            sessions.extend(wt.sessions)
    for repo in provider.codex_monitor.repositories:
        for wt in repo.worktrees:
            sessions.extend(wt.sessions)
    return sessions


def _get_watcher_for_provider(provider, provider_name: str):
    """Return the correct file watcher for the given provider name."""
    if provider_name == "codex":
        return provider.codex_watcher
    return provider.claude_watcher


def _parse_result_to_monitor_state(pr: object) -> SessionMonitorState:
    """Convert a ParseResult (claude or codex) to a SessionMonitorState."""
    state = SessionMonitorState()
    state.model = getattr(pr, "model", "")
    state.input_tokens = getattr(pr, "last_input_tokens", 0)
    state.output_tokens = getattr(pr, "last_output_tokens", 0)
    state.total_output_tokens = getattr(pr, "total_output_tokens", 0)
    state.cache_read_tokens = getattr(pr, "cache_read_tokens", 0)
    state.cache_creation_tokens = getattr(pr, "cache_creation_tokens", 0)
    state.message_count = getattr(pr, "message_count", 0)
    state.tool_calls = dict(getattr(pr, "tool_calls", {}))
    state.recent_activities = list(getattr(pr, "recent_activities", []))
    state.git_branch = getattr(pr, "git_branch", "")

    # Backward-compat scalar fields (properties on ParseResult)
    state.has_mermaid_content = getattr(pr, "has_mermaid_content", False)
    state.plan_file_path = getattr(pr, "plan_file_path", "")
    state.plan_content = getattr(pr, "plan_content", "")

    # List fields
    plans = getattr(pr, "plans", [])
    state.plans = [
        PlanInfo(file_path=p.file_path, content=p.content, timestamp=p.timestamp.isoformat())
        for p in plans
    ]
    diagrams = getattr(pr, "mermaid_diagrams", [])
    state.mermaid_diagrams = [
        MermaidDiagramInfo(source=d.source, file_path=d.file_path, timestamp=d.timestamp.isoformat())
        for d in diagrams
    ]

    started = getattr(pr, "session_started_at", None)
    if started:
        state.session_started_at = started
    last = getattr(pr, "last_activity_at", None)
    if last:
        state.last_activity_at = last

    current = getattr(pr, "current_status", None)
    if current is not None:
        state.status = current.status
        state.pending_tool_use = current.pending_tool_use

    return state


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("", response_model=SessionListResponse)
async def list_sessions(request: Request) -> SessionListResponse:
    """List all sessions across all repositories and providers."""
    prov = _get_provider(request)
    sessions = _collect_all_sessions(prov)
    # Sort by most recent activity first
    sessions.sort(key=lambda s: s.last_activity_at, reverse=True)
    return SessionListResponse(sessions=sessions, total=len(sessions))


@router.get("/names/all", response_model=AllSessionNamesResponse)
async def get_all_session_names(request: Request) -> AllSessionNamesResponse:
    """Get all custom session names."""
    prov = _get_provider(request)
    names = await prov.metadata_store.get_all_custom_names()
    return AllSessionNamesResponse(names=names)


def _find_session_file(provider: object, session_id: str) -> str | None:
    """Find the JSONL file path for a session across all providers."""
    session, _, _ = _find_session_across_providers(provider, session_id)
    if session and session.session_file_path:
        return session.session_file_path

    # Fallback: search known project directories
    from agent_hub.services.path_utils import encode_project_path, get_claude_projects_dir

    try:
        settings = provider.settings  # type: ignore[union-attr]
        claude_path = settings.claude_data_path
    except AttributeError:
        claude_path = "~/.claude"

    projects_dir = get_claude_projects_dir(claude_path)
    if projects_dir.is_dir():
        for project_dir in projects_dir.iterdir():
            if not project_dir.is_dir():
                continue
            candidate = project_dir / f"{session_id}.jsonl"
            if candidate.is_file():
                return str(candidate)

    return None


def _read_jsonl_paginated(
    file_path: str,
    offset: int = 0,
    limit: int = 50,
) -> tuple[list[HistoryEntry], int, bool]:
    """Read a JSONL file with pagination (newest first).

    Returns (entries, total_lines, has_more).
    """
    path = Path(file_path)
    if not path.is_file():
        return [], 0, False

    # Read all lines to get total count (JSONL files are line-based)
    with open(path, encoding="utf-8", errors="replace") as f:
        all_lines = f.readlines()

    total = len(all_lines)

    # Reverse for newest-first
    all_lines.reverse()

    # Apply pagination
    page = all_lines[offset : offset + limit]
    has_more = (offset + limit) < total

    entries: list[HistoryEntry] = []
    for i, raw_line in enumerate(page):
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        try:
            data = json.loads(raw_line)
            if isinstance(data, dict):
                line_num = total - offset - i  # original line number (1-based)
                entries.append(HistoryEntry(
                    line=line_num,
                    type=str(data.get("type", "")),
                    data=data,
                ))
        except (json.JSONDecodeError, ValueError):
            continue

    return entries, total, has_more


@router.get("/{session_id}/history", response_model=SessionHistoryResponse)
async def get_session_history(
    session_id: str,
    request: Request,
    offset: int = 0,
    limit: int = 50,
) -> SessionHistoryResponse:
    """Get paginated raw JSONL history for a session (newest first)."""
    prov = _get_provider(request)
    file_path = _find_session_file(prov, session_id)
    if file_path is None:
        raise HTTPException(status_code=404, detail=f"Session file not found: {session_id}")

    limit = min(limit, 200)  # cap page size
    entries, total, has_more = _read_jsonl_paginated(file_path, offset, limit)

    return SessionHistoryResponse(
        session_id=session_id,
        entries=entries,
        total_lines=total,
        offset=offset,
        has_more=has_more,
    )


@router.get("/{session_id}", response_model=SessionDetailResponse)
async def get_session(session_id: str, request: Request) -> SessionDetailResponse:
    """Get details for a specific session."""
    prov = _get_provider(request)
    session, repo_path, provider_name = _find_session_across_providers(prov, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    return SessionDetailResponse(
        session=session,
        repository_path=repo_path,
        provider=provider_name,
    )


@router.post("/{session_id}/monitor", response_model=MonitorStateResponse)
async def start_monitoring(
    session_id: str,
    body: MonitorStartRequest,
    request: Request,
) -> MonitorStateResponse:
    """Start monitoring a session's JSONL file for live state updates."""
    prov = _get_provider(request)
    watcher = _get_watcher_for_provider(prov, body.provider)

    try:
        await watcher.start_monitoring(
            session_id=session_id,
            project_path=body.project_path,
            session_file_path=body.session_file_path,
        )
    except Exception as exc:
        logger.exception("Failed to start monitoring session %s", session_id)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to start monitoring: {exc}",
        ) from exc

    state = await watcher.get_state(session_id)
    return MonitorStateResponse(
        session_id=session_id,
        state=state,
        monitoring=True,
    )


@router.delete("/{session_id}/monitor", response_model=MonitorStateResponse)
async def stop_monitoring(
    session_id: str,
    request: Request,
    provider: Literal["claude", "codex"] = "claude",
) -> MonitorStateResponse:
    """Stop monitoring a session."""
    prov = _get_provider(request)
    watcher = _get_watcher_for_provider(prov, provider)

    try:
        await watcher.stop_monitoring(session_id)
    except Exception as exc:
        logger.exception("Failed to stop monitoring session %s", session_id)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to stop monitoring: {exc}",
        ) from exc

    return MonitorStateResponse(
        session_id=session_id,
        state=None,
        monitoring=False,
    )


@router.get("/{session_id}/state", response_model=MonitorStateResponse)
async def get_monitor_state(
    session_id: str,
    request: Request,
    provider: Literal["claude", "codex"] = "claude",
) -> MonitorStateResponse:
    """Get the current monitor state for a session.

    Returns live state if monitored, otherwise falls back to the
    parse cache (full JSONL parse, cached by file size).
    """
    prov = _get_provider(request)
    watcher = _get_watcher_for_provider(prov, provider)
    state = await watcher.get_state(session_id)
    if state is not None:
        return MonitorStateResponse(
            session_id=session_id,
            state=state,
            monitoring=True,
        )

    # Cache fallback for non-monitored sessions
    file_path = _find_session_file(prov, session_id)
    if file_path is not None:
        pr = prov.parse_cache.get(session_id, file_path, provider)
        if pr is not None:
            return MonitorStateResponse(
                session_id=session_id,
                state=_parse_result_to_monitor_state(pr),
                monitoring=False,
            )

    return MonitorStateResponse(session_id=session_id, state=None, monitoring=False)


@router.post("/{session_id}/refresh", response_model=MonitorStateResponse)
async def refresh_session_state(
    session_id: str,
    request: Request,
    provider: Literal["claude", "codex"] = "claude",
) -> MonitorStateResponse:
    """Force-refresh the monitor state for a session by re-parsing from scratch."""
    prov = _get_provider(request)
    watcher = _get_watcher_for_provider(prov, provider)

    try:
        await watcher.refresh_state(session_id)
    except Exception as exc:
        logger.exception("Failed to refresh session state %s", session_id)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to refresh state: {exc}",
        ) from exc

    state = await watcher.get_state(session_id)
    return MonitorStateResponse(
        session_id=session_id,
        state=state,
        monitoring=state is not None,
    )


# ---------------------------------------------------------------------------
# Session names
# ---------------------------------------------------------------------------


@router.put("/{session_id}/name", response_model=SessionNameResponse)
async def set_session_name(
    session_id: str,
    body: SessionNameRequest,
    request: Request,
) -> SessionNameResponse:
    """Set or clear a custom name for a session.

    Send ``{"name": "my name"}`` to set, or ``{"name": null}`` / ``{"name": ""}`` to clear.
    """
    prov = _get_provider(request)
    name = body.name.strip() if body.name else None
    if name:
        await prov.metadata_store.upsert_metadata(session_id, custom_name=name)
    else:
        await prov.metadata_store.upsert_metadata(session_id, custom_name=None)
        name = None
    return SessionNameResponse(session_id=session_id, name=name)


# ---------------------------------------------------------------------------
# Plan
# ---------------------------------------------------------------------------


class PlanResponse(BaseModel):
    """Response containing plan file content."""

    session_id: str
    plan_file_path: str | None = None
    plan_content: str | None = None


@router.get("/{session_id}/plan", response_model=PlanResponse)
async def get_session_plan(
    session_id: str,
    request: Request,
) -> PlanResponse:
    """Get the plan file content for a session (no monitoring required).

    Checks monitored state first, then falls back to the parse cache.
    """
    prov = _get_provider(request)

    # First check if session is monitored and has plan content already
    for watcher in (prov.claude_watcher, prov.codex_watcher):
        state = await watcher.get_state(session_id)
        if state is not None and state.plan_content:
            return PlanResponse(
                session_id=session_id,
                plan_file_path=state.plan_file_path,
                plan_content=state.plan_content,
            )

    # Not monitored — use parse cache
    file_path = _find_session_file(prov, session_id)
    if file_path is not None:
        pr = prov.parse_cache.get(session_id, file_path)
        if pr is not None and pr.plan_content:
            return PlanResponse(
                session_id=session_id,
                plan_file_path=pr.plan_file_path,
                plan_content=pr.plan_content,
            )

    return PlanResponse(session_id=session_id)


@router.post("/create-pending", response_model=CreatePendingSessionResponse)
async def create_pending_session(
    body: CreatePendingSessionRequest,
    request: Request,
) -> CreatePendingSessionResponse:
    """Create a pre-seeded session JSONL file with a pending user message.

    This allows a new session to appear in the repository tree immediately,
    before Claude has started or responded.  The caller can then resume the
    session via ``--resume <session_id>`` and Claude will respond to the
    pending message.
    """
    from agent_hub.services.path_utils import encode_project_path, get_claude_projects_dir

    prov = _get_provider(request)
    session_id = str(uuid.uuid4())
    msg_uuid = str(uuid.uuid4())
    now = datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")

    project_path = str(Path(body.project_path).resolve())
    encoded = encode_project_path(project_path)
    projects_dir = get_claude_projects_dir(prov.settings.claude_data_path)
    session_dir = projects_dir / encoded
    session_dir.mkdir(parents=True, exist_ok=True)
    session_file = session_dir / f"{session_id}.jsonl"

    snapshot_entry = {
        "type": "file-history-snapshot",
        "messageId": msg_uuid,
        "snapshot": {
            "messageId": msg_uuid,
            "trackedFileBackups": {},
            "timestamp": now,
        },
        "isSnapshotUpdate": False,
    }
    user_entry = {
        "parentUuid": None,
        "isSidechain": False,
        "userType": "external",
        "cwd": project_path,
        "sessionId": session_id,
        "type": "user",
        "message": {
            "role": "user",
            "content": body.prompt or "No context",
        },
        "uuid": msg_uuid,
        "timestamp": now,
        "todos": [],
        "permissionMode": "default",
    }

    with open(session_file, "w") as f:
        f.write(json.dumps(snapshot_entry) + "\n")
        f.write(json.dumps(user_entry) + "\n")

    # Refresh session list so the new file is discovered immediately
    try:
        await prov.claude_monitor.refresh_sessions()
    except Exception:
        logger.exception("Failed to refresh sessions after creating pending session")

    return CreatePendingSessionResponse(
        session_id=session_id,
        session_file_path=str(session_file),
    )
