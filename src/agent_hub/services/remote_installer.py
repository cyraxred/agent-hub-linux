"""Remote installer — deploy Agent Hub on a remote host via SSH.

Builds a wheel locally, transfers it over SFTP, then runs an install script
that sets up a venv and systemd user service.  All operations are idempotent.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shlex
import subprocess
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
    import asyncssh  # type: ignore[import-untyped]

logger = logging.getLogger(__name__)

# Relative path under $HOME on the remote — only used in shell commands where
# the remote shell expands $HOME.  Never used as a Python filesystem path.
_REMOTE_INSTALL_RELPATH = ".local/share/agent-hub"

INSTALL_SCRIPT = r"""#!/bin/bash
set -e

INSTALL_DIR="$HOME/.local/share/agent-hub"
WHEEL_NAME="${1:?wheel filename argument required}"

# 1. Check Python 3.11+
if ! python3 --version 2>/dev/null | grep -qE '3\.(1[1-9]|[2-9][0-9])'; then
    echo "ERROR: Python 3.11+ required (found: $(python3 --version 2>&1 || echo 'none'))"
    exit 1
fi
echo "Python: $(python3 --version)"

# 2. Create/update venv
echo "Setting up virtualenv..."
python3 -m venv "$INSTALL_DIR/.venv"
source "$INSTALL_DIR/.venv/bin/activate"

# 3. Install agent-hub from the exact wheel
WHEEL_PATH="$INSTALL_DIR/$WHEEL_NAME"
if [ ! -f "$WHEEL_PATH" ]; then
    echo "ERROR: Wheel not found: $WHEEL_PATH"
    exit 1
fi
echo "Installing agent-hub from $WHEEL_NAME..."
pip install --upgrade "$WHEEL_PATH" 2>&1

# 4. Write systemd user service (if systemd is available)
if command -v systemctl &>/dev/null; then
    echo "Configuring systemd user service..."
    mkdir -p ~/.config/systemd/user
    cat > ~/.config/systemd/user/agent-hub.service << UNIT
[Unit]
Description=Agent Hub
After=network.target

[Service]
ExecStart=$INSTALL_DIR/.venv/bin/agent-hub
Environment=AGENT_HUB_API_HOST=127.0.0.1
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
UNIT

    # 5. Enable and start (user-level systemd, no root)
    systemctl --user daemon-reload
    systemctl --user enable --now agent-hub

    # 6. Enable lingering so service runs without active login session
    loginctl enable-linger "$(whoami)" 2>/dev/null || true

    echo "Systemd service enabled and started."
else
    echo "WARN: systemd not found — skipping service setup. Run agent-hub manually."
fi

echo "OK: Agent Hub installed and running"
"""


class InstallStatus(TypedDict):
    installed: bool
    running: bool
    version: str | None


def _local_version() -> str:
    """Read the local project version from pyproject.toml."""
    import tomllib

    pyproject = Path(__file__).resolve().parents[3] / "pyproject.toml"
    if pyproject.is_file():
        with open(pyproject, "rb") as f:
            data = tomllib.load(f)
        return data.get("project", {}).get("version", "unknown")
    return "unknown"


def _project_root() -> Path:
    """Return the project root directory (where pyproject.toml lives)."""
    return Path(__file__).resolve().parents[3]


def _find_or_build_wheel() -> Path:
    """Return a wheel, building one only if the source tree is available.

    In dev the full source tree is present and we can rebuild.  In production
    installs (no pyproject.toml / no ``build`` package) we fall back to any
    existing wheel in dist/.
    """
    root = _project_root()
    dist_dir = root / "dist"
    pyproject = root / "pyproject.toml"

    # Collect existing wheels
    existing = sorted(dist_dir.glob("agent_hub-*.whl"), key=lambda p: p.stat().st_mtime)

    # If we don't have a source tree to build from, use whatever we have
    if not pyproject.is_file():
        if existing:
            return existing[-1]
        raise RuntimeError(
            "No wheel found in dist/ and no source tree available to build one"
        )

    # Check if rebuild needed: any .py file newer than the newest wheel
    newest_whl = existing[-1] if existing else None
    newest_whl_mtime = newest_whl.stat().st_mtime if newest_whl else 0.0

    src_dir = root / "src"
    need_rebuild = newest_whl is None
    if not need_rebuild:
        for src_file in src_dir.rglob("*.py"):
            if src_file.stat().st_mtime > newest_whl_mtime:
                need_rebuild = True
                break

    if need_rebuild:
        logger.info("Building wheel...")
        dist_dir.mkdir(exist_ok=True)
        # Clean old wheels
        for old in dist_dir.glob("agent_hub-*.whl"):
            old.unlink()
        subprocess.run(
            ["python3", "-m", "build", "--wheel", "--outdir", str(dist_dir)],
            cwd=str(root),
            check=True,
            capture_output=True,
            text=True,
        )
        existing = list(dist_dir.glob("agent_hub-*.whl"))

    if not existing:
        raise RuntimeError("No wheel found in dist/ after build")
    return existing[-1]


async def _resolve_remote_home(conn: asyncssh.SSHClientConnection) -> str:
    """Run ``echo $HOME`` on the remote and return the path."""
    result = await conn.run('echo "$HOME"', check=True)
    return result.stdout.strip()  # type: ignore[union-attr]


def _remote_install_dir(remote_home: str) -> str:
    """Build the absolute remote install path and return it shell-quoted."""
    return shlex.quote(f"{remote_home}/{_REMOTE_INSTALL_RELPATH}")


class RemoteInstaller:
    """Install / update / check Agent Hub on a remote host via SSH."""

    @staticmethod
    async def install(
        conn: asyncssh.SSHClientConnection,
        on_output: Callable[[str], Awaitable[None]],
    ) -> bool:
        """Build wheel, transfer via SFTP, run install script.

        *on_output* is an async callback that receives chunks of output text.
        Returns True on success, False on failure.
        """
        try:
            # 1. Build wheel locally
            await on_output("Building wheel locally...\n")
            start = time.monotonic()
            wheel_path = await asyncio.get_running_loop().run_in_executor(
                None, _find_or_build_wheel
            )
            elapsed = time.monotonic() - start
            await on_output(f"Wheel built: {wheel_path.name} ({elapsed:.1f}s)\n")

            # 2. Resolve remote $HOME and derive the install directory
            remote_home = await _resolve_remote_home(conn)
            q_dir = _remote_install_dir(remote_home)
            # Unquoted path for SFTP operations (SFTP uses raw paths, not shell)
            raw_dir = f"{remote_home}/{_REMOTE_INSTALL_RELPATH}"

            await on_output("Creating remote directory...\n")
            await conn.run(f"mkdir -p {q_dir}", check=True)

            # 3. SFTP wheel + install script
            await on_output("Transferring files via SFTP...\n")
            async with conn.start_sftp_client() as sftp:  # type: ignore[union-attr]
                await sftp.makedirs(raw_dir, exist_ok=True)  # type: ignore[call-arg]

                # Remove old wheels
                try:
                    for entry in await sftp.listdir(raw_dir):
                        if entry.endswith(".whl"):
                            await sftp.remove(f"{raw_dir}/{entry}")
                except Exception:
                    pass

                # Upload wheel
                remote_whl = f"{raw_dir}/{wheel_path.name}"
                await sftp.put(str(wheel_path), remote_whl)
                await on_output(f"Uploaded {wheel_path.name}\n")

                # Upload install script
                remote_script = f"{raw_dir}/install.sh"
                import tempfile

                with tempfile.NamedTemporaryFile(
                    mode="w", suffix=".sh", delete=False
                ) as tmp:
                    tmp.write(INSTALL_SCRIPT)
                    tmp_path = tmp.name
                try:
                    await sftp.put(tmp_path, remote_script)
                    q_script = shlex.quote(remote_script)
                    await conn.run(f"chmod +x {q_script}", check=True)
                finally:
                    os.unlink(tmp_path)

                await on_output("Files transferred.\n")

            # 4. Execute install script, streaming output
            await on_output("Running install script...\n")
            await on_output("---\n")

            q_script = shlex.quote(f"{raw_dir}/install.sh")
            q_whl_name = shlex.quote(wheel_path.name)
            process = await conn.create_process(
                f"bash {q_script} {q_whl_name}",
            )

            stdout = process.stdout  # type: ignore[union-attr]
            stderr = process.stderr  # type: ignore[union-attr]

            async def _read_stream(stream: object) -> None:
                reader = stream  # type: ignore[assignment]
                while True:
                    line = await reader.readline()  # type: ignore[union-attr]
                    if not line:
                        break
                    await on_output(line)

            await asyncio.gather(
                _read_stream(stdout),
                _read_stream(stderr),
            )

            await process.wait()  # type: ignore[union-attr]
            exit_status: int = process.exit_status  # type: ignore[union-attr,assignment]

            await on_output("---\n")
            if exit_status == 0:
                await on_output("Install completed successfully.\n")
                return True
            else:
                await on_output(f"Install failed (exit code {exit_status}).\n")
                return False

        except Exception as exc:
            await on_output(f"ERROR: {exc}\n")
            logger.exception("Remote install failed")
            return False

    @staticmethod
    async def check_status(conn: asyncssh.SSHClientConnection) -> InstallStatus:
        """Check if agent-hub is installed and running on the remote."""
        status: InstallStatus = {"installed": False, "running": False, "version": None}

        try:
            remote_home = await _resolve_remote_home(conn)
            q_pip = shlex.quote(
                f"{remote_home}/{_REMOTE_INSTALL_RELPATH}/.venv/bin/pip"
            )

            # Check installed version via pip show
            result = await conn.run(
                f'{q_pip} show agent-hub 2>/dev/null | grep "^Version:"',
            )
            stdout = (result.stdout or "").strip()  # type: ignore[union-attr]
            if stdout and result.exit_status == 0:  # type: ignore[union-attr]
                status["installed"] = True
                # "Version: 0.1.0" → "0.1.0"
                status["version"] = stdout.split(":", 1)[-1].strip()

            # Check if systemd service is running
            result = await conn.run(
                "systemctl --user is-active agent-hub 2>/dev/null",
            )
            active = (result.stdout or "").strip()  # type: ignore[union-attr]
            if active == "active":
                status["running"] = True

        except Exception as exc:
            logger.debug("check_status failed: %s", exc)

        return status

    @staticmethod
    async def uninstall(
        conn: asyncssh.SSHClientConnection,
        on_output: Callable[[str], Awaitable[None]],
    ) -> bool:
        """Stop the service and remove the installation."""
        try:
            remote_home = await _resolve_remote_home(conn)
            q_dir = _remote_install_dir(remote_home)

            await on_output("Stopping agent-hub service...\n")
            await conn.run(
                "systemctl --user stop agent-hub 2>/dev/null; "
                "systemctl --user disable agent-hub 2>/dev/null; "
                "rm -f ~/.config/systemd/user/agent-hub.service; "
                "systemctl --user daemon-reload 2>/dev/null",
            )
            await on_output("Removing installation...\n")
            await conn.run(f"rm -rf {q_dir}")
            await on_output("OK: Agent Hub uninstalled.\n")
            return True
        except Exception as exc:
            await on_output(f"ERROR: {exc}\n")
            return False

    @staticmethod
    def local_version() -> str:
        return _local_version()
