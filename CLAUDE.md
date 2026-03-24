# Agent Hub Linux

## Setup Notes

### Terminal Session Connectivity

To allow Agent Hub to connect to interactive Claude sessions started from the command line, users should add a tmux wrapper to their shell configuration (`~/.bashrc` or `~/.zshrc`):

```bash
claude() { tmux new-session -d -s "claude-$$" command claude "$@" && tmux attach -t "claude-$$"; }
```

This transparently launches Claude inside a tmux session, allowing Agent Hub to attach via `tmux attach`. The user experience is identical to typing `claude` directly — no root or additional tooling required.

### Installing Agent Hub as a Service

When a user asks to install Agent Hub as a systemd service (locally or on a remote machine), follow the logic in `src/agent_hub/services/remote_installer.py`:

1. Create a venv at `~/.local/share/agent-hub/.venv`
2. Install into the venv — `pip install .` from the repo root (or `pip install --upgrade <wheel>` for remote installs where the wheel is transferred via SFTP)
3. Write a systemd user service at `~/.config/systemd/user/agent-hub.service`
4. Enable with `systemctl --user enable --now agent-hub` and `loginctl enable-linger`

**Important — confirm the access method with the user before setting `AGENT_HUB_API_HOST`:**

- **SSH tunnel access** (remote install via the built-in installer, or user will connect through SSH): set `AGENT_HUB_API_HOST=127.0.0.1`. The service only listens on localhost; the SSH tunnel forwards traffic securely.
- **Direct network access** (user will connect directly over the network, e.g. LAN): set `AGENT_HUB_API_HOST=0.0.0.0`. The service listens on all interfaces. The user is responsible for firewall rules and should enable TLS.
