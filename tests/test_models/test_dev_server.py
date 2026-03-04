"""Tests for agent_hub.models.dev_server module."""

from __future__ import annotations

import pytest
from pydantic import TypeAdapter

from agent_hub.models.dev_server import (
    DetectedProject,
    DevServerState,
    DevServerStateDetecting,
    DevServerStateFailed,
    DevServerStateIdle,
    DevServerStateReady,
    DevServerStateStarting,
    DevServerStateStopping,
    DevServerStateWaitingForReady,
    ProjectFramework,
)


# ---------- ProjectFramework ----------


class TestProjectFramework:
    """Tests for the ProjectFramework enum."""

    def test_values(self) -> None:
        assert ProjectFramework.vite == "vite"
        assert ProjectFramework.nextjs == "nextjs"
        assert ProjectFramework.create_react_app == "create_react_app"
        assert ProjectFramework.angular == "angular"
        assert ProjectFramework.vue_cli == "vue_cli"
        assert ProjectFramework.astro == "astro"
        assert ProjectFramework.static_html == "static_html"
        assert ProjectFramework.unknown == "unknown"

    def test_requires_dev_server_true(self) -> None:
        for fw in [
            ProjectFramework.vite,
            ProjectFramework.nextjs,
            ProjectFramework.create_react_app,
            ProjectFramework.angular,
            ProjectFramework.vue_cli,
            ProjectFramework.astro,
        ]:
            assert fw.requires_dev_server is True, f"{fw} should require dev server"

    def test_requires_dev_server_false(self) -> None:
        assert ProjectFramework.static_html.requires_dev_server is False
        assert ProjectFramework.unknown.requires_dev_server is False


# ---------- DetectedProject ----------


class TestDetectedProject:
    """Tests for the DetectedProject model."""

    def test_creation(self) -> None:
        project = DetectedProject(
            framework=ProjectFramework.vite,
            command="npx",
            arguments=["vite", "--port", "5173"],
            default_port=5173,
            readiness_patterns=["Local:"],
        )
        assert project.framework == ProjectFramework.vite
        assert project.command == "npx"
        assert project.arguments == ["vite", "--port", "5173"]
        assert project.default_port == 5173
        assert project.readiness_patterns == ["Local:"]

    def test_defaults(self) -> None:
        project = DetectedProject(
            framework=ProjectFramework.unknown,
            command="npm",
        )
        assert project.arguments == []
        assert project.default_port == 3000
        assert project.readiness_patterns == []

    def test_serialization_roundtrip(self) -> None:
        project = DetectedProject(
            framework=ProjectFramework.nextjs,
            command="npm",
            arguments=["run", "dev"],
        )
        data = project.model_dump()
        restored = DetectedProject.model_validate(data)
        assert restored.framework == ProjectFramework.nextjs


# ---------- DevServerState ----------


class TestDevServerState:
    """Tests for the DevServerState discriminated union."""

    def test_idle(self) -> None:
        state = DevServerStateIdle()
        assert state.kind == "idle"

    def test_detecting(self) -> None:
        state = DevServerStateDetecting()
        assert state.kind == "detecting"

    def test_starting(self) -> None:
        state = DevServerStateStarting(message="Starting vite...")
        assert state.kind == "starting"
        assert state.message == "Starting vite..."

    def test_starting_default_message(self) -> None:
        state = DevServerStateStarting()
        assert state.message == ""

    def test_waiting_for_ready(self) -> None:
        state = DevServerStateWaitingForReady()
        assert state.kind == "waiting_for_ready"

    def test_ready(self) -> None:
        state = DevServerStateReady(url="http://localhost:5173")
        assert state.kind == "ready"
        assert state.url == "http://localhost:5173"

    def test_failed(self) -> None:
        state = DevServerStateFailed(error="Port in use")
        assert state.kind == "failed"
        assert state.error == "Port in use"

    def test_stopping(self) -> None:
        state = DevServerStateStopping()
        assert state.kind == "stopping"

    def test_discriminated_union_all_variants(self) -> None:
        adapter = TypeAdapter(DevServerState)
        variants = [
            {"kind": "idle"},
            {"kind": "detecting"},
            {"kind": "starting", "message": ""},
            {"kind": "waiting_for_ready"},
            {"kind": "ready", "url": "http://localhost:3000"},
            {"kind": "failed", "error": "oops"},
            {"kind": "stopping"},
        ]
        for v in variants:
            parsed = adapter.validate_python(v)
            assert parsed.kind == v["kind"]

    def test_serialization_roundtrip(self) -> None:
        adapter = TypeAdapter(DevServerState)
        state = DevServerStateReady(url="http://localhost:3000")
        data = adapter.dump_python(state)
        restored = adapter.validate_python(data)
        assert restored.kind == "ready"
        assert restored.url == "http://localhost:3000"  # type: ignore[union-attr]
