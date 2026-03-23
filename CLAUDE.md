# Agent Hub Linux

## Setup Notes

### Terminal Session Connectivity

To allow Agent Hub to connect to interactive Claude sessions started from the command line, users should add a tmux wrapper to their shell configuration (`~/.bashrc` or `~/.zshrc`):

```bash
claude() { tmux new-session -d -s "claude-$$" command claude "$@" && tmux attach -t "claude-$$"; }
```

This transparently launches Claude inside a tmux session, allowing Agent Hub to attach via `tmux attach`. The user experience is identical to typing `claude` directly — no root or additional tooling required.
