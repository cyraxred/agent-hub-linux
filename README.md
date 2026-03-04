# Agent Hub Linux

A Linux desktop application for real-time monitoring and management of **Claude Code** and **Codex CLI** sessions. Built as a complete ground-up rebuild of [AgentHub](https://github.com/jamesrochabrun/AgentHub) by James Rochabrun — the original macOS-native SwiftUI application that pioneered the concept of a unified agent session manager.

This project owes its existence to AgentHub's vision and UI design. While AgentHub targets macOS with Swift and SwiftUI, Agent Hub Linux is an entirely new implementation using Python + React, bringing the same core experience to Linux.

## Relationship to AgentHub

[AgentHub](https://github.com/jamesrochabrun/AgentHub) is the original project by [James Rochabrun](https://github.com/jamesrochabrun) — a beautifully crafted native macOS app for managing AI coding sessions. This project was deeply inspired by its feature set and user experience. We recommend checking out the original if you're on macOS.

### Replicated Features

The following AgentHub features have been rebuilt for Linux:

- **Multi-provider support** — side-by-side Claude Code and Codex session management
- **Real-time monitoring** — file-system watchers (watchdog) without polling
- **Embedded terminal** — full PTY support via xterm.js and WebSocket streaming
- **Inline diff review** — split-pane viewing of staged/unstaged changes and branch diffs
- **Git worktree management** — create/remove branches and isolated worktrees
- **Multi-session launcher** — launch parallel sessions across worktrees
- **Mermaid diagram rendering** — visualize session-generated diagrams
- **Plan view** — markdown rendering of session plans
- **Global search** — fuzzy search across all session files
- **Usage statistics** — token tracking, cost estimates, and daily activity charts
- **Command palette** — quick navigation (Ctrl+K)
- **Privacy-first** — all data stays local, no external transmission

### Features Not Yet Implemented

- Multiple layout modes (single, list, 2-column, 3-column grid)
- Custom YAML themes with hot-reload
- Notification sounds for tool call approvals
- Web preview with auto-detection and live-reload
- Direct feedback to Claude from diff view

### New Features in This Project

- **Cross-platform architecture** — Python/React stack runs on any Linux distribution
- **WebSocket-first communication** — bidirectional real-time updates between backend and frontend via discriminated union messages
- **Pydantic type generation** — shared type definitions auto-generated from Python models to TypeScript, ensuring type safety across the stack
- **Async Python backend** — fully async FastAPI with SQLAlchemy, aiosqlite, and uvicorn
- **Context window visualization** — token budget bar showing input/output/cache usage
- **Session history browser** — paginated raw JSONL viewer (newest-first)
- **Approval timeout detection** — tracks pending tool approvals with timeout handling
- **Token cache awareness** — separately tracks prompt cache reads and creations
- **Headless mode** — runs as API-only server when no GUI is available
- **System tray integration** — optional pystray support for background operation

## Tech Stack

### Backend
- **Python 3.11+** with strict Pyright type checking
- **FastAPI** + **Uvicorn** (async ASGI server)
- **SQLAlchemy 2** + **aiosqlite** (async SQLite)
- **Pydantic 2** (data validation and settings)
- **watchdog** (file system monitoring)
- **pywebview** (native desktop window)
- **pystray** (optional system tray)

### Frontend
- **React 18** with **TypeScript 5**
- **Vite 5** (build tooling)
- **Zustand 4** (state management)
- **xterm.js 5** with WebGL addon (terminal emulation)
- **react-markdown 9** (markdown rendering)
- **Mermaid 10** (diagram rendering)

## Requirements

- Linux (any modern distribution)
- Python 3.11 or later
- Node.js 18+ (for frontend build)
- Claude Code CLI (installed and authenticated)
- Codex CLI (optional)

## Installation

```bash
# Clone the repository
git clone https://github.com/cyraxred/agent-hub-linux.git
cd agent-hub-linux

# Install all dependencies
make install

# Generate TypeScript types from Python models
make typegen

# Build the frontend
make build-frontend

# Run the application
make run
```

## Development

```bash
make dev              # Run backend + frontend dev servers concurrently
make dev-backend      # Backend only with hot reload (port 18080)
make dev-frontend     # Frontend only with Vite dev server

make lint             # Check code style (ruff)
make typecheck        # Type checking (pyright + tsc)
make test             # Run test suite
make typegen          # Regenerate frontend types from backend models
```

## Session Data

Agent Hub reads session data from standard CLI locations:

- **Claude Code:** `~/.claude/projects/{encoded-path}/{sessionId}.jsonl`
- **Codex:** `~/.codex/` directories

Application data is stored in XDG-compliant paths:
- **Database:** `~/.local/share/agent-hub/agent-hub.db`
- **Settings:** `~/.config/agent-hub/settings.json`

## License

MIT License — see [LICENSE](LICENSE) for details.

## Acknowledgments

This project is a complete rebuild inspired by [AgentHub](https://github.com/jamesrochabrun/AgentHub) by [James Rochabrun](https://github.com/jamesrochabrun). The original AgentHub established the vision for a unified AI agent session manager, and this project carries that vision to the Linux desktop. Thank you, James, for the inspiration and the excellent UI design that guided this work.
