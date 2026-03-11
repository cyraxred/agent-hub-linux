"""Path utilities for Claude/Codex session file discovery."""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def encode_project_path(project_path: str) -> str:
    """Encode a project path for use as a Claude session directory name.

    Claude stores sessions under ~/.claude/projects/{encoded_path}/.
    The encoding replaces '/' with '-' after stripping the leading slash.
    Example: /home/user/myproject -> -home-user-myproject
    """
    # Strip trailing slash and replace / with -
    cleaned = project_path.rstrip("/")
    if cleaned.startswith("/"):
        cleaned = cleaned[1:]
    return "-" + cleaned.replace("/", "-") if cleaned else ""


def decode_project_path(encoded: str) -> str:
    """Decode an encoded project path back to the original filesystem path.

    Reverses the encoding from encode_project_path.
    Example: -home-user-myproject -> /home/user/myproject
    """
    if not encoded or encoded == "-":
        return "/"
    # Remove leading dash, replace remaining dashes with /
    # This is a best-effort heuristic—ambiguity exists when directory names contain dashes
    stripped = encoded.lstrip("-")
    return "/" + stripped.replace("-", "/")


def get_claude_projects_dir(claude_data_path: str) -> Path:
    """Return the Claude projects directory."""
    return Path(claude_data_path).expanduser() / "projects"


def get_codex_sessions_dir(codex_data_path: str) -> Path:
    """Return the Codex sessions directory."""
    return Path(codex_data_path).expanduser() / "sessions"


def get_history_file(data_path: str) -> Path:
    """Return the history.jsonl file path."""
    return Path(data_path).expanduser() / "history.jsonl"


def get_stats_cache_file(data_path: str) -> Path:
    """Return the stats-cache.json file path."""
    return Path(data_path).expanduser() / "stats-cache.json"


# A resumable session must contain at least one of these types.
# "user" is included so that pre-seeded pending sessions (created before Claude
# has responded) are discovered immediately in the repository tree.
_RESUMABLE_TYPES = frozenset({"system", "assistant", "progress", "summary", "user"})

# Cache: path -> is_conversation.  Files that are not conversations today could
# become conversations if they're still being written to, so we only cache True
# results permanently.  False results use mtime to detect changes.
_conversation_file_cache: dict[str, tuple[bool, float]] = {}


def _is_conversation_file(path: Path) -> bool:
    """Check whether a .jsonl file contains a resumable conversation.

    Claude Code writes auxiliary files (file-history-snapshot, queue-operation)
    and sometimes incomplete sessions (user-only) that share the same UUID-named
    .jsonl format but are not resumable.  A resumable session must have at least
    one ``system``, ``assistant``, ``progress``, or ``summary`` entry.

    Results are cached.  True results are cached permanently (a conversation
    doesn't stop being one).  False results are re-checked when the file's
    mtime changes (the file may still be written to).
    """
    key = str(path)
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return False

    cached = _conversation_file_cache.get(key)
    if cached is not None:
        cached_result, cached_mtime = cached
        if cached_result or cached_mtime == mtime:
            return cached_result

    result = False
    try:
        with open(path, "rb") as f:
            # Read enough to find an assistant/system entry; these typically
            # appear within the first few KB of a real conversation.
            head = f.read(16384)
        for line in head.split(b"\n"):
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                if isinstance(data, dict) and data.get("type") in _RESUMABLE_TYPES:
                    result = True
                    break
            except (json.JSONDecodeError, ValueError):
                continue
    except OSError:
        pass

    _conversation_file_cache[key] = (result, mtime)
    return result


def find_session_files(projects_dir: Path) -> list[Path]:
    """Find top-level .jsonl session files that contain real conversations.

    Excludes subdirectories (e.g. subagents/) and auxiliary files that only
    contain file-history-snapshot or queue-operation entries.
    """
    if not projects_dir.is_dir():
        return []
    return sorted(p for p in projects_dir.glob("*.jsonl") if _is_conversation_file(p))


def detect_needs_attention(path: Path) -> str | None:
    """Check if a session file ends in a state that needs user attention.

    Reads the last ~8 KB to find the final JSONL entry and checks:
    - 'approval': last entry is an assistant message with pending tool_use blocks
    - 'question': last entry is an assistant AskUserQuestion tool_use

    Returns None if no attention needed.
    """
    try:
        size = path.stat().st_size
    except OSError:
        return None

    read_size = min(size, 8192)
    try:
        with open(path, "rb") as f:
            if size > read_size:
                f.seek(size - read_size)
            tail = f.read()
    except OSError:
        return None

    # Find the last complete JSON line
    lines = tail.split(b"\n")
    last_entry: dict[str, object] | None = None
    for raw in reversed(lines):
        raw = raw.strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                last_entry = data
                break
        except (json.JSONDecodeError, ValueError):
            continue

    if last_entry is None:
        return None

    entry_type = last_entry.get("type", "")
    if entry_type != "assistant":
        return None

    msg = last_entry.get("message")
    if not isinstance(msg, dict):
        return None

    content = msg.get("content")
    if not isinstance(content, list):
        return None

    has_tool_use = False
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "tool_use":
            has_tool_use = True
            name = str(block.get("name", ""))
            if name.lower() in ("askuserquestion", "ask_user_question"):
                return "question"

    if has_tool_use:
        return "approval"

    return None


def session_id_from_path(session_file: Path) -> str:
    """Extract session ID from a session file path (stem of file name)."""
    return session_file.stem


def project_path_from_session_dir(session_dir: Path, projects_dir: Path) -> str:
    """Extract the project path from a session directory relative to projects dir.

    The session_dir is like ~/.claude/projects/{encoded_path}/
    We want to decode {encoded_path} back to the original project path.
    """
    try:
        rel = session_dir.relative_to(projects_dir)
        encoded = str(rel.parts[0]) if rel.parts else ""
        return decode_project_path(encoded)
    except ValueError:
        return str(session_dir)
