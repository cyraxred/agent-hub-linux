"""Settings routes for reading and updating user preferences."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/settings", tags=["settings"])

# Default location for the user settings file.
_DEFAULT_SETTINGS_DIR = Path.home() / ".config" / "agent-hub"
_DEFAULT_SETTINGS_FILE = _DEFAULT_SETTINGS_DIR / "settings.json"


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class SettingsResponse(BaseModel):
    """Response containing the full user settings dictionary."""

    settings: dict[str, Any]


class SettingsUpdateRequest(BaseModel):
    """Partial-update body -- only the provided keys are merged."""

    settings: dict[str, Any]


class SettingsUpdateResponse(BaseModel):
    """Confirmation after updating settings."""

    success: bool = True
    settings: dict[str, Any]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _settings_file_path(request: Request) -> Path:
    """Determine the settings file path.

    Uses the provider's settings object if available, otherwise falls back to
    the XDG-compliant default.
    """
    try:
        prov = request.app.state.provider
        app_settings = prov.settings
        return app_settings.settings_file_path
    except AttributeError:
        return _DEFAULT_SETTINGS_FILE


def _load_settings(path: Path) -> dict[str, Any]:
    """Load settings from disk.  Returns an empty dict on any error."""
    if not path.is_file():
        return {}
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
        return {}
    except (json.JSONDecodeError, OSError):
        logger.exception("Failed to load settings from %s", path)
        return {}


def _save_settings(path: Path, data: dict[str, Any]) -> None:
    """Persist settings to disk, creating parent directories as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, sort_keys=False, default=str) + "\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


class CLIStatusEntry(BaseModel):
    """Availability info for a single CLI provider."""

    key: str
    label: str
    color: str
    available: bool
    path: str | None = None


class CLIStatusResponse(BaseModel):
    """Response listing all known CLI providers and their availability."""

    providers: list[CLIStatusEntry]


_PROVIDER_META: list[dict[str, str]] = [
    {"key": "claude", "command": "claude", "label": "Claude", "color": "#d97706"},
    {"key": "codex", "command": "codex", "label": "Codex", "color": "#10b981"},
]


@router.get("/cli-status", response_model=CLIStatusResponse)
async def cli_status(request: Request) -> CLIStatusResponse:
    """Check which CLI tools (claude, codex) are installed."""
    from agent_hub.services.terminal_launcher import find_cli_command

    try:
        additional_paths = request.app.state.provider.settings.additional_cli_paths
    except AttributeError:
        additional_paths = []

    entries: list[CLIStatusEntry] = []
    for meta in _PROVIDER_META:
        cli_path = find_cli_command(meta["command"], additional_paths=additional_paths)
        entries.append(CLIStatusEntry(
            key=meta["key"],
            label=meta["label"],
            color=meta["color"],
            available=cli_path is not None,
            path=cli_path,
        ))

    return CLIStatusResponse(providers=entries)


@router.get("", response_model=SettingsResponse)
async def get_settings(request: Request) -> SettingsResponse:
    """Get the current user settings."""
    path = _settings_file_path(request)
    return SettingsResponse(settings=_load_settings(path))


@router.put("", response_model=SettingsUpdateResponse)
async def update_settings(
    body: SettingsUpdateRequest,
    request: Request,
) -> SettingsUpdateResponse:
    """Update user settings (partial merge).

    Only the keys present in ``body.settings`` are updated; all other
    existing keys are preserved.
    """
    path = _settings_file_path(request)

    try:
        current = _load_settings(path)
        current.update(body.settings)
        _save_settings(path, current)
    except Exception as exc:
        logger.exception("Failed to save settings")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to save settings: {exc}",
        ) from exc

    return SettingsUpdateResponse(success=True, settings=current)
