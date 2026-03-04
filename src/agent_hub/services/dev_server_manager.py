"""Dev server lifecycle management ported from DevServerManager.swift."""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import signal
import socket
from pathlib import Path

from agent_hub.config.defaults import DEV_SERVER_READINESS_TIMEOUT
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

logger = logging.getLogger(__name__)

# Framework detection and config
_FRAMEWORK_CONFIGS: dict[ProjectFramework, dict[str, object]] = {
    ProjectFramework.vite: {
        "command": "npm",
        "args": ["run", "dev", "--", "--port"],
        "default_port": 5173,
        "patterns": ["Local:", "ready in"],
    },
    ProjectFramework.nextjs: {
        "command": "npm",
        "args": ["run", "dev", "--", "-p"],
        "default_port": 3000,
        "patterns": ["Ready", "started server"],
    },
    ProjectFramework.create_react_app: {
        "command": "npm",
        "args": ["start"],
        "default_port": 3000,
        "patterns": ["Compiled successfully", "You can now view"],
    },
    ProjectFramework.angular: {
        "command": "npm",
        "args": ["start", "--", "--port"],
        "default_port": 4200,
        "patterns": ["Angular Live Development Server"],
    },
    ProjectFramework.vue_cli: {
        "command": "npm",
        "args": ["run", "serve", "--", "--port"],
        "default_port": 8080,
        "patterns": ["App running at"],
    },
    ProjectFramework.astro: {
        "command": "npm",
        "args": ["run", "dev", "--", "--port"],
        "default_port": 4321,
        "patterns": ["Local:", "astro"],
    },
    ProjectFramework.static_html: {
        "command": "python3",
        "args": ["-m", "http.server"],
        "default_port": 8000,
        "patterns": ["Serving HTTP"],
    },
}


def detect_framework(project_path: str) -> ProjectFramework:
    """Detect the web framework used in a project."""
    pkg_json = Path(project_path) / "package.json"
    if not pkg_json.is_file():
        if (Path(project_path) / "index.html").is_file():
            return ProjectFramework.static_html
        return ProjectFramework.unknown

    try:
        import json

        data = json.loads(pkg_json.read_text())
        deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}

        if "vite" in deps:
            return ProjectFramework.vite
        if "next" in deps:
            return ProjectFramework.nextjs
        if "react-scripts" in deps:
            return ProjectFramework.create_react_app
        if "@angular/core" in deps:
            return ProjectFramework.angular
        if "@vue/cli-service" in deps:
            return ProjectFramework.vue_cli
        if "astro" in deps:
            return ProjectFramework.astro
    except (OSError, ValueError):
        pass

    return ProjectFramework.unknown


def _find_available_port(preferred: int) -> int:
    """Find an available port, preferring the given port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", preferred))
            return preferred
        except OSError:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]


class DevServerManager:
    """Manages dev server processes for web preview."""

    def __init__(self) -> None:
        self._servers: dict[str, asyncio.subprocess.Process] = {}
        self._states: dict[str, DevServerState] = {}

    def state(self, project_path: str) -> DevServerState:
        return self._states.get(project_path, DevServerStateIdle())

    async def start_server(self, project_path: str) -> None:
        """Start a dev server for a project."""
        if project_path in self._servers:
            return

        self._states[project_path] = DevServerStateDetecting()

        framework = detect_framework(project_path)
        if not framework.requires_dev_server:
            self._states[project_path] = DevServerStateFailed(
                error="No dev server needed for this project"
            )
            return

        config = _FRAMEWORK_CONFIGS.get(framework)
        if config is None:
            self._states[project_path] = DevServerStateFailed(
                error=f"No config for framework: {framework}"
            )
            return

        command = str(config["command"])
        args = list(config.get("args", []))  # type: ignore[arg-type]
        default_port = int(config.get("default_port", 3000))  # type: ignore[arg-type]
        patterns = list(config.get("patterns", []))  # type: ignore[arg-type]

        cmd_path = shutil.which(command)
        if cmd_path is None:
            self._states[project_path] = DevServerStateFailed(
                error=f"Command not found: {command}"
            )
            return

        port = _find_available_port(default_port)

        # Build args with port
        full_args = [cmd_path] + [str(a) for a in args]
        if framework != ProjectFramework.create_react_app:
            full_args.append(str(port))

        env = dict(os.environ)
        if framework == ProjectFramework.create_react_app:
            env["PORT"] = str(port)
            env["BROWSER"] = "none"

        self._states[project_path] = DevServerStateStarting(
            message=f"Starting {framework.value} on port {port}..."
        )

        try:
            proc = await asyncio.create_subprocess_exec(
                *full_args,
                cwd=project_path,
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
            )
            self._servers[project_path] = proc
            self._states[project_path] = DevServerStateWaitingForReady()

            # Monitor for readiness
            asyncio.create_task(
                self._wait_for_ready(project_path, proc, patterns, port)
            )

        except OSError as e:
            self._states[project_path] = DevServerStateFailed(error=str(e))

    async def _wait_for_ready(
        self,
        project_path: str,
        proc: asyncio.subprocess.Process,
        patterns: list[str],
        port: int,
    ) -> None:
        """Wait for the dev server to become ready."""
        try:
            deadline = asyncio.get_event_loop().time() + DEV_SERVER_READINESS_TIMEOUT
            while asyncio.get_event_loop().time() < deadline:
                if proc.returncode is not None:
                    self._states[project_path] = DevServerStateFailed(
                        error="Dev server exited unexpectedly"
                    )
                    return

                # Read output for patterns
                for stream in [proc.stdout, proc.stderr]:
                    if stream is None:
                        continue
                    try:
                        data = await asyncio.wait_for(stream.read(4096), timeout=0.5)
                        if data:
                            text = data.decode("utf-8", errors="replace")
                            for pattern in patterns:
                                if pattern.lower() in text.lower():
                                    self._states[project_path] = DevServerStateReady(
                                        url=f"http://127.0.0.1:{port}"
                                    )
                                    return
                    except asyncio.TimeoutError:
                        continue

            self._states[project_path] = DevServerStateFailed(
                error="Dev server readiness timeout"
            )
        except Exception as e:
            self._states[project_path] = DevServerStateFailed(error=str(e))

    async def stop_server(self, project_path: str) -> None:
        """Stop a running dev server."""
        proc = self._servers.pop(project_path, None)
        if proc is None:
            return
        self._states[project_path] = DevServerStateStopping()
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            proc.kill()
        self._states[project_path] = DevServerStateIdle()

    async def stop_all(self) -> None:
        for path in list(self._servers.keys()):
            await self.stop_server(path)
