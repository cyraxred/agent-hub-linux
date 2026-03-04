"""Application settings ported from Swift AgentHubConfiguration.swift."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings


class SessionProviderKind(StrEnum):
    """Supported CLI session providers."""

    claude = "claude"
    codex = "codex"


class StatsDisplayMode(StrEnum):
    """How stats are displayed."""

    menu_bar = "menu_bar"
    popover = "popover"


class Settings(BaseSettings):
    """Application configuration, loaded from env / settings file."""

    model_config = {"env_prefix": "AGENT_HUB_"}

    # Data paths
    claude_data_path: str = Field(
        default_factory=lambda: str(Path.home() / ".claude")
    )
    codex_data_path: str = Field(
        default_factory=lambda: str(Path.home() / ".codex")
    )

    # XDG-compliant app paths
    app_data_dir: str = Field(
        default_factory=lambda: str(Path.home() / ".local" / "share" / "agent-hub")
    )
    app_config_dir: str = Field(
        default_factory=lambda: str(Path.home() / ".config" / "agent-hub")
    )

    # Server
    api_host: str = "127.0.0.1"
    api_port: int = 18080

    # CLI commands
    cli_command: str = "claude"
    codex_command: str = "codex"

    # Feature flags
    enable_debug_logging: bool = False
    session_provider: SessionProviderKind = SessionProviderKind.claude
    stats_display_mode: StatsDisplayMode = StatsDisplayMode.popover

    # Approval detection
    approval_timeout_seconds: int = 5

    # Additional CLI search paths
    additional_cli_paths: list[str] = Field(default_factory=list)

    @property
    def db_path(self) -> Path:
        """SQLite database path."""
        return Path(self.app_data_dir) / "agent-hub.db"

    @property
    def settings_file_path(self) -> Path:
        """User settings JSON file path."""
        return Path(self.app_config_dir) / "settings.json"

    @property
    def themes_dir(self) -> Path:
        """Custom themes directory."""
        return Path(self.app_config_dir) / "themes"

    def ensure_dirs(self) -> None:
        """Create application directories if they don't exist."""
        Path(self.app_data_dir).mkdir(parents=True, exist_ok=True)
        Path(self.app_config_dir).mkdir(parents=True, exist_ok=True)
        self.themes_dir.mkdir(parents=True, exist_ok=True)
