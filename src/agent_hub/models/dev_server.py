"""Dev server detection and state models."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, Field, computed_field


class ProjectFramework(StrEnum):
    """Detected project framework type."""

    vite = "vite"
    nextjs = "nextjs"
    create_react_app = "create_react_app"
    angular = "angular"
    vue_cli = "vue_cli"
    astro = "astro"
    static_html = "static_html"
    unknown = "unknown"

    @property
    def requires_dev_server(self) -> bool:
        """Whether this framework requires a dev server to preview."""
        match self:
            case ProjectFramework.static_html | ProjectFramework.unknown:
                return False
            case _:
                return True


class DetectedProject(BaseModel, frozen=True):
    """A detected project with its framework and launch configuration."""

    framework: ProjectFramework
    command: str
    arguments: list[str] = Field(default_factory=list)
    default_port: int = 3000
    readiness_patterns: list[str] = Field(default_factory=list)


# --- DevServerState tagged union ---


class DevServerStateIdle(BaseModel, frozen=True):
    """Dev server is idle."""

    kind: Literal["idle"] = "idle"


class DevServerStateDetecting(BaseModel, frozen=True):
    """Dev server is detecting project framework."""

    kind: Literal["detecting"] = "detecting"


class DevServerStateStarting(BaseModel, frozen=True):
    """Dev server is starting."""

    kind: Literal["starting"] = "starting"
    message: str = ""


class DevServerStateWaitingForReady(BaseModel, frozen=True):
    """Dev server is waiting to become ready."""

    kind: Literal["waiting_for_ready"] = "waiting_for_ready"


class DevServerStateReady(BaseModel, frozen=True):
    """Dev server is ready and serving."""

    kind: Literal["ready"] = "ready"
    url: str


class DevServerStateFailed(BaseModel, frozen=True):
    """Dev server failed to start."""

    kind: Literal["failed"] = "failed"
    error: str


class DevServerStateStopping(BaseModel, frozen=True):
    """Dev server is stopping."""

    kind: Literal["stopping"] = "stopping"


DevServerState = Annotated[
    DevServerStateIdle
    | DevServerStateDetecting
    | DevServerStateStarting
    | DevServerStateWaitingForReady
    | DevServerStateReady
    | DevServerStateFailed
    | DevServerStateStopping,
    Field(discriminator="kind"),
]
