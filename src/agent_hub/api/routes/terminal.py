"""Terminal routes for launching, resizing, and terminating PTY sessions."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from agent_hub.services.process_registry import ProcessRegistry
from agent_hub.services.terminal_launcher import (
    TerminalProcess,
    build_cli_args,
    find_cli_command,
    resize_terminal,
    spawn_terminal,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/terminal", tags=["terminal"])


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class TerminalLaunchRequest(BaseModel):
    """Body for launching a new terminal session."""

    command: str = "claude"
    project_path: str = ""
    session_id: str | None = None
    resume: bool = False
    prompt: str | None = None


class TerminalLaunchResponse(BaseModel):
    """Response after launching a terminal."""

    key: str
    pid: int
    fd: int
    session_id: str | None = None
    project_path: str


class TerminalResizeRequest(BaseModel):
    """Body for resizing a terminal."""

    rows: int = 24
    cols: int = 80


class TerminalResizeResponse(BaseModel):
    """Response after resizing a terminal."""

    key: str
    success: bool = True


class TerminalTerminateResponse(BaseModel):
    """Response after terminating a terminal."""

    key: str
    terminated: bool = True


class TerminalInfoEntry(BaseModel):
    """Summary information for a running terminal."""

    key: str
    pid: int
    fd: int
    session_id: str | None = None
    project_path: str = ""


class TerminalListResponse(BaseModel):
    """Response listing all active terminals."""

    terminals: list[TerminalInfoEntry]
    total: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_registry(request: Request) -> ProcessRegistry:
    """Retrieve the process registry from app state.

    The registry is stored either directly as ``request.app.state.process_registry``
    or inside the provider.
    """
    try:
        return request.app.state.process_registry
    except AttributeError:
        pass
    try:
        return request.app.state.provider.process_registry
    except AttributeError:
        pass
    # Lazily create a registry if not present
    registry = ProcessRegistry()
    request.app.state.process_registry = registry
    return registry


def _make_key(session_id: str | None, project_path: str) -> str:
    """Generate a stable key for a terminal process."""
    if session_id:
        return f"term-{session_id}"
    return f"term-{abs(hash(project_path))}"


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/launch", response_model=TerminalLaunchResponse)
async def launch_terminal(
    body: TerminalLaunchRequest,
    request: Request,
) -> TerminalLaunchResponse:
    """Launch a new terminal with a PTY.

    Spawns the requested CLI command (e.g. ``claude``, ``codex``) inside
    a pseudo-terminal. The returned ``key`` and ``fd`` can be used by
    the WebSocket terminal handler to bridge xterm.js.
    """
    registry = _get_registry(request)

    # Resolve the CLI command
    try:
        settings = request.app.state.provider.settings
        additional_paths = settings.additional_cli_paths
    except AttributeError:
        additional_paths = []

    cli_path = find_cli_command(body.command, additional_paths=additional_paths)
    if cli_path is None:
        raise HTTPException(
            status_code=404,
            detail=f"CLI command not found: {body.command}",
        )

    cwd = body.project_path if body.project_path and Path(body.project_path).is_dir() else None

    args = build_cli_args(
        cli_path,
        session_id=body.session_id,
        resume=body.resume,
        prompt=body.prompt,
    )

    try:
        proc = spawn_terminal(args, cwd=cwd)
    except Exception as exc:
        logger.exception("Failed to spawn terminal")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to spawn terminal: {exc}",
        ) from exc

    proc.session_id = body.session_id
    proc.project_path = body.project_path

    key = _make_key(body.session_id, body.project_path)
    registry.register(key, proc)

    return TerminalLaunchResponse(
        key=key,
        pid=proc.pid,
        fd=proc.fd,
        session_id=body.session_id,
        project_path=body.project_path,
    )


@router.post("/{key}/resize", response_model=TerminalResizeResponse)
async def resize_terminal_endpoint(
    key: str,
    body: TerminalResizeRequest,
    request: Request,
) -> TerminalResizeResponse:
    """Resize a running terminal's PTY."""
    registry = _get_registry(request)
    proc = registry.get(key)
    if proc is None:
        raise HTTPException(status_code=404, detail=f"Terminal not found: {key}")

    try:
        resize_terminal(proc.fd, body.rows, body.cols)
    except Exception as exc:
        logger.exception("Failed to resize terminal %s", key)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to resize terminal: {exc}",
        ) from exc

    return TerminalResizeResponse(key=key, success=True)


@router.delete("/{key}", response_model=TerminalTerminateResponse)
async def terminate_terminal(
    key: str,
    request: Request,
) -> TerminalTerminateResponse:
    """Terminate a running terminal process."""
    registry = _get_registry(request)
    proc = registry.get(key)
    if proc is None:
        raise HTTPException(status_code=404, detail=f"Terminal not found: {key}")

    try:
        registry.terminate(key)
    except Exception as exc:
        logger.exception("Failed to terminate terminal %s", key)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to terminate terminal: {exc}",
        ) from exc

    return TerminalTerminateResponse(key=key, terminated=True)


@router.get("", response_model=TerminalListResponse)
async def list_terminals(request: Request) -> TerminalListResponse:
    """List all active terminal processes."""
    registry = _get_registry(request)

    # Clean up dead processes before listing
    registry.cleanup_orphaned()

    terminals: list[TerminalInfoEntry] = []
    for key in registry.keys():
        proc = registry.get(key)
        if proc is not None:
            terminals.append(
                TerminalInfoEntry(
                    key=key,
                    pid=proc.pid,
                    fd=proc.fd,
                    session_id=proc.session_id,
                    project_path=proc.project_path,
                )
            )

    return TerminalListResponse(terminals=terminals, total=len(terminals))
