# Session Lifecycle Bugs & Findings

## Architecture Overview (relevant parts)

- **Monitoring** (file watcher) and **selection** (UI) are decoupled — switching sessions does not stop the file watcher
- **`sessionStates`** — Zustand store, populated by WebSocket file watcher events, holds live session status
- **`repositories`** — Zustand store, populated by periodic API fetches, holds the session tree
- **Terminal** — PTY process spawned by AgentHub via `claude --resume {session_id}`, bridged over WebSocket to xterm.js

---

## Bug 1: Terminal kills Claude process on session switch

**File:** `frontend/src/components/terminal/EmbeddedTerminal.tsx`

When `EmbeddedTerminal` unmounts (user switches to another session), its cleanup runs:

```typescript
return () => {
  wsRef.current?.close();
  if (terminalKey) {
    api.terminal.kill(terminalKey);  // ← sends SIGTERM to the Claude process
  }
};
```

This kills the Claude process. Any pending tool call or `AskQuestionTool` waiting for user input is cancelled.

**What should happen:** only the WebSocket should close on unmount. The PTY process should remain alive in the `ProcessRegistry`. The backend already supports this — `registry.get(key)` reattaches to an existing process on the next `launch` call.

---

## Bug 2: Terminal reopens the wrong session

**Flow:**
1. Terminal is killed (Bug 1)
2. Registry entry is removed
3. User reopens terminal → `launch` spawns new process: `claude --resume {session_id}` with `cwd = project_path`
4. Claude resolves sessions relative to a project folder derived from cwd: `~/.claude/projects/{hash(cwd)}/`
5. If `project_path` is the **repo root** but the session file lives under a **worktree path** (different hash), Claude cannot find the session
6. Claude falls back to the most recently active session for that project path — a different existing session

**Result:** wrong session is resumed, wrong session becomes "active", original session is orphaned.

---

## Bug 3: Repo shows active count bubble with no visible session

**Root cause:** `sessionStates` and `repositories` are independent stores with no reconciliation.

When a session disappears from the `repositories` tree (deleted, expired, or orphaned after Bug 2), its entry in `sessionStates` is never removed. The repo-level active count reads from `sessionStates`, finds the ghost entry, and displays a green bubble. The tree renders from `repositories` and shows nothing.

**Fix:** after each `repositories` refresh, remove any `sessionStates` entries whose session ID no longer exists in the tree.

---

## Bug 4: Two Claude processes can write to the same session file

If the user already has Claude running in an external terminal for a given session, and then opens that session's terminal in AgentHub, the `ProcessRegistry` has no entry for it (it didn't spawn it), so it spawns a new `claude --resume` process. Both processes append JSONL to the same session file with no coordination — undefined behavior / potential corruption.

**Note:** AgentHub does guard against spawning duplicates for terminals *it* launched (registry check), but has no awareness of externally-launched Claude processes.

---

## Summary of fixes

| Bug | Fix |
|---|---|
| Terminal kills Claude on switch | Remove `api.terminal.kill()` from `EmbeddedTerminal` cleanup; only close WebSocket |
| Wrong session resumed | Pass the correct worktree `project_path` (not repo root) to terminal launch; verify session file location before spawning |
| Stale repo count bubble | Reconcile `sessionStates` against `repositories` after each tree refresh |
| External process conflict | Out of scope for now; document as known limitation |
