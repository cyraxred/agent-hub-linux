"""Terminal routes for launching, resizing, and terminating PTY sessions."""

from __future__ import annotations

import asyncio
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


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


async def _write_prompt_deferred(fd: int, prompt: str, delay: float = 3.0) -> None:
    """Write a prompt to a PTY after a delay, allowing the CLI to become ready."""
    await asyncio.sleep(delay)
    try:
        os.write(fd, (prompt + "\n").encode("utf-8"))
    except OSError:
        logger.debug("Failed to write deferred prompt to fd %d", fd)


@router.post("/launch", response_model=TerminalLaunchResponse)
async def launch_terminal(
    body: TerminalLaunchRequest,
    request: Request,
) -> TerminalLaunchResponse:
    """Launch a new terminal with a PTY, or reuse an existing one.

    If a terminal for the same session already exists, it is reused.
    When a ``prompt`` is provided, it is written to the PTY stdin
    (after a short delay for new terminals, immediately for existing ones)
    rather than passed as a CLI argument, so Claude receives it as user input.
    """
    registry = _get_registry(request)
    session_id = body.session_id

    # Check for an existing terminal (only when a session_id is provided)
    existing = registry.get(session_id) if session_id else None
    if existing is not None:
        # Terminal already running — send prompt as stdin if provided
        if body.prompt:
            try:
                os.write(existing.fd, (body.prompt + "\n").encode("utf-8"))
            except OSError:
                logger.debug("Failed to write prompt to existing terminal %s", session_id)
        return TerminalLaunchResponse(
            key=session_id,
            pid=existing.pid,
            fd=existing.fd,
            session_id=existing.session_id,
            project_path=existing.project_path,
        )

    # Resume requires a session_id.
    if body.resume and not session_id:
        raise HTTPException(
            status_code=400,
            detail="Cannot resume without a session_id.",
        )

    # Guard: reject if the session has a running process that isn't connectable.
    # Resuming such a session would fork the JSONL transcript.
    if body.resume:
        try:
            sm = request.app.state.provider.session_manager
            session = sm.get_session(body.session_id)
            if session and session.is_running and not session.is_connectable:
                cat = session.process.category if session.process else "unknown"
                pid = session.process.pid if session.process else 0
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"Session {body.session_id} has a running {cat} process "
                        f"(pid {pid}) that cannot be connected to. "
                        "Resuming would fork the session transcript."
                    ),
                )
        except HTTPException:
            raise
        except Exception:
            # Fallback to direct tracker check
            try:
                tracker = request.app.state.provider.process_tracker
                proc_info = tracker.get_process_for_session(body.session_id)
                if proc_info is not None and proc_info.category in ("user", "third_party"):
                    raise HTTPException(
                        status_code=409,
                        detail=(
                            f"Session {body.session_id} has a running {proc_info.category} process "
                            f"(pid {proc_info.pid}) that cannot be connected to. "
                            "Resuming would fork the session transcript."
                        ),
                    )
            except HTTPException:
                raise
            except AttributeError:
                pass

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

    # Don't pass prompt as CLI arg — we'll write it to stdin after Claude is ready
    args = build_cli_args(
        cli_path,
        session_id=body.session_id,
        resume=body.resume,
    )

    try:
        proc = spawn_terminal(args, cwd=cwd)
    except Exception as exc:
        logger.exception("Failed to spawn terminal")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to spawn terminal: {exc}",
        ) from exc

    proc.session_id = session_id
    proc.project_path = body.project_path

    if session_id:
        registry.register(session_id, proc)

        # Notify process tracker of hub-launched process
        try:
            tracker = request.app.state.provider.process_tracker
            tracker.notify_hub_launch(proc.pid, session_id)
        except AttributeError:
            pass

        # Notify session manager
        try:
            sm = request.app.state.provider.session_manager
            asyncio.ensure_future(sm.handle_terminal_registered(session_id))
        except (AttributeError, Exception):
            pass

    # Write prompt to stdin after delay so Claude has time to start
    if body.prompt:
        asyncio.create_task(_write_prompt_deferred(proc.fd, body.prompt))

    return TerminalLaunchResponse(
        key=session_id,
        pid=proc.pid,
        fd=proc.fd,
        session_id=session_id,
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

    # Notify process tracker before terminating
    try:
        tracker = request.app.state.provider.process_tracker
        tracker.notify_hub_terminate(proc.pid)
    except AttributeError:
        pass

    # Notify session manager
    if proc.session_id:
        try:
            sm = request.app.state.provider.session_manager
            asyncio.ensure_future(sm.handle_terminal_unregistered(proc.session_id))
        except (AttributeError, Exception):
            pass

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
