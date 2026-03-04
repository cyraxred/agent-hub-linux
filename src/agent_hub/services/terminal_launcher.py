"""Terminal launcher — PTY spawning and CLI arg construction."""

from __future__ import annotations

import logging
import os
import pty
import shutil
import signal
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class TerminalProcess:
    """Tracks a spawned terminal process."""

    pid: int
    fd: int
    session_id: str | None = None
    project_path: str = ""


def find_cli_command(command: str, additional_paths: list[str] | None = None) -> str | None:
    """Find a CLI command (claude/codex) on PATH or additional paths."""
    result = shutil.which(command)
    if result:
        return result

    search_paths = list(additional_paths or [])
    # Common locations
    search_paths.extend([
        os.path.expanduser("~/.local/bin"),
        "/usr/local/bin",
        os.path.expanduser("~/.nvm/versions/node"),
    ])

    for base in search_paths:
        candidate = os.path.join(base, command)
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
        # Check NVM node directories
        if "nvm" in base and os.path.isdir(base):
            for version_dir in os.listdir(base):
                candidate = os.path.join(base, version_dir, "bin", command)
                if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                    return candidate

    return None


def build_cli_args(
    command: str,
    session_id: str | None = None,
    resume: bool = False,
    dangerously_skip_permissions: bool = False,
    prompt: str | None = None,
) -> list[str]:
    """Build CLI arguments for launching claude/codex.

    Note: project_path is NOT passed as -p (that means "print mode" in
    Claude Code, which exits after one response). Instead the caller
    should set cwd to project_path so claude picks up the project
    context from the working directory.
    """
    args = [command]
    if resume and session_id:
        args.extend(["--resume", session_id])
    if dangerously_skip_permissions:
        args.append("--dangerously-skip-permissions")
    if prompt:
        args.append(prompt)
    return args


def spawn_terminal(
    args: list[str],
    cwd: str | None = None,
    env: dict[str, str] | None = None,
) -> TerminalProcess:
    """Spawn a process with a PTY.

    Returns a TerminalProcess with the child PID and master FD.
    """
    merged_env = dict(os.environ)
    if env:
        merged_env.update(env)

    # Remove env vars that prevent nested Claude Code sessions.
    # AgentHub spawns independent sessions, not nested ones.
    for key in ("CLAUDECODE", "CLAUDE_CODE_SESSION"):
        merged_env.pop(key, None)

    pid, fd = pty.openpty()

    child_pid = os.fork()
    if child_pid == 0:
        # Child process
        os.close(pid)
        os.setsid()
        import fcntl
        import termios

        fcntl.ioctl(fd, termios.TIOCSCTTY, 0)
        os.dup2(fd, 0)
        os.dup2(fd, 1)
        os.dup2(fd, 2)
        if fd > 2:
            os.close(fd)
        if cwd:
            os.chdir(cwd)
        os.execvpe(args[0], args, merged_env)
    else:
        # Parent process
        os.close(fd)
        return TerminalProcess(pid=child_pid, fd=pid)


def resize_terminal(fd: int, rows: int, cols: int) -> None:
    """Resize a PTY terminal."""
    import fcntl
    import struct
    import termios

    winsize = struct.pack("HHHH", rows, cols, 0, 0)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, winsize)


def terminate_process(pid: int) -> None:
    """Gracefully terminate a process (SIGTERM then SIGKILL)."""
    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        try:
            os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
