import { create } from 'zustand';
import type { SelectedRepository, SessionMonitorState, SessionHistoryEntry } from '@/types/generated';
import { api } from '@/api/client';
import { useNotificationsStore } from '@/store/notifications';

type Provider = string;

/** Lightweight pub/sub for streaming history entries from WS to SessionHistoryView. */
type HistoryAppendListener = (
  sessionId: string,
  entries: SessionHistoryEntry[],
  totalLines: number,
) => void;

class HistoryAppendBus {
  private listeners = new Set<HistoryAppendListener>();

  subscribe(listener: HistoryAppendListener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  notify(sessionId: string, entries: SessionHistoryEntry[], totalLines: number) {
    for (const listener of this.listeners) {
      listener(sessionId, entries, totalLines);
    }
  }
}

export const historyAppendBus = new HistoryAppendBus();

interface SessionsState {
  /** Repository tree (repos → worktrees → sessions). */
  repositories: SelectedRepository[];
  /** Session states keyed by session ID (from WS session_state_update). */
  sessionStates: Record<string, SessionMonitorState>;
  /** Session IDs currently being monitored. */
  monitoredSessionIds: Set<string>;
  /** Subscription info for monitored sessions (session_id -> {projectPath, sessionFilePath}). */
  monitoredSessionInfo: Record<string, { projectPath: string; sessionFilePath: string }>;

  selectedSessionId: string | null;
  selectedRepositoryPath: string | null;
  activeProvider: Provider;
  loading: boolean;
  error: string | null;
  /** User-assigned custom names for sessions (session_id -> name). */
  customSessionNames: Record<string, string>;
  /** Session ID to reveal/focus in the sidebar tree (cleared after handling). */
  revealSessionId: string | null;

  // Actions
  fetchRepositories: (provider?: Provider) => Promise<void>;
  addRepository: (path: string, provider?: Provider) => Promise<void>;
  removeRepository: (path: string, provider?: Provider) => Promise<void>;
  selectRepository: (path: string | null) => void;
  selectSession: (id: string | null) => void;
  setActiveProvider: (provider: Provider) => void;
  refreshSessions: () => Promise<void>;
  revealSession: (id: string) => void;
  clearReveal: () => void;

  startMonitoring: (
    sessionId: string,
    projectPath: string,
    sessionFilePath?: string,
  ) => Promise<void>;
  stopMonitoring: (sessionId: string) => Promise<void>;
  refreshSessionState: (sessionId: string) => Promise<void>;

  /** Load persisted custom names from backend. */
  loadSessionNames: () => Promise<void>;
  /** Set or clear a custom name for a session (persists to backend). */
  setSessionName: (sessionId: string, name: string | null) => void;

  /** Called by WS hook when session_state_update arrives. */
  setSessionState: (sessionId: string, state: SessionMonitorState) => void;
  /** Called by WS hook when sessions_updated arrives. */
  setRepositories: (repos: SelectedRepository[]) => void;
}

export const useSessionsStore = create<SessionsState>((set, get) => ({
  repositories: [],
  sessionStates: {},
  monitoredSessionIds: new Set(),
  monitoredSessionInfo: {},
  selectedSessionId: null,
  selectedRepositoryPath: null,
  activeProvider: 'claude',
  loading: false,
  error: null,
  customSessionNames: {},
  revealSessionId: null,

  fetchRepositories: async (provider) => {
    set({ loading: true, error: null });
    try {
      const repositories = await api.repositories.list(provider ?? get().activeProvider);
      set({ repositories, loading: false });
      useNotificationsStore.getState().syncFromRepositories(repositories);
    } catch (err) {
      set({ error: (err as Error).message, loading: false });
    }
  },

  addRepository: async (path, provider) => {
    set({ loading: true, error: null });
    try {
      await api.repositories.add(path, provider ?? get().activeProvider);
      // Re-fetch the full tree so the new repo shows with all its sessions
      const repositories = await api.repositories.list(provider ?? get().activeProvider);
      set({ repositories, loading: false });
    } catch (err) {
      set({ error: (err as Error).message, loading: false });
    }
  },

  removeRepository: async (path, provider) => {
    set({ error: null });
    try {
      await api.repositories.remove(path, provider ?? get().activeProvider);
      set((s) => ({
        repositories: s.repositories.filter((r) => r.path !== path),
        selectedRepositoryPath:
          s.selectedRepositoryPath === path ? null : s.selectedRepositoryPath,
      }));
    } catch (err) {
      set({ error: (err as Error).message });
    }
  },

  selectRepository: (path) => set({ selectedRepositoryPath: path }),
  selectSession: (id) => set({ selectedSessionId: id }),
  revealSession: (id) => set({ revealSessionId: id }),
  clearReveal: () => set({ revealSessionId: null }),
  setActiveProvider: (provider) => {
    set({ activeProvider: provider });
    get().fetchRepositories(provider);
  },

  refreshSessions: async () => {
    set({ error: null });
    try {
      await api.repositories.refresh(get().activeProvider);
      await get().fetchRepositories();
    } catch (err) {
      set({ error: (err as Error).message });
    }
  },

  startMonitoring: async (sessionId, projectPath, sessionFilePath) => {
    set({ error: null });
    try {
      const resp = await api.sessions.startMonitoring(
        sessionId,
        projectPath,
        sessionFilePath,
        get().activeProvider,
      );
      set((s) => {
        const ids = new Set(s.monitoredSessionIds);
        ids.add(sessionId);
        const states = { ...s.sessionStates };
        if (resp.state) states[sessionId] = resp.state;
        const info = { ...s.monitoredSessionInfo };
        info[sessionId] = { projectPath, sessionFilePath: sessionFilePath ?? '' };
        return { monitoredSessionIds: ids, sessionStates: states, monitoredSessionInfo: info };
      });
    } catch (err) {
      set({ error: (err as Error).message });
    }
  },

  stopMonitoring: async (sessionId) => {
    set({ error: null });
    try {
      await api.sessions.stopMonitoring(sessionId, get().activeProvider);
      set((s) => {
        const ids = new Set(s.monitoredSessionIds);
        ids.delete(sessionId);
        const info = { ...s.monitoredSessionInfo };
        delete info[sessionId];
        // Keep sessionStates[sessionId] so the UI retains last-known state
        return { monitoredSessionIds: ids, monitoredSessionInfo: info };
      });
    } catch (err) {
      set({ error: (err as Error).message });
    }
  },

  refreshSessionState: async (sessionId) => {
    set({ error: null });
    try {
      const state = await api.sessions.refreshState(sessionId, get().activeProvider);
      if (state) {
        set((s) => ({
          sessionStates: { ...s.sessionStates, [sessionId]: state },
        }));
      }
    } catch (err) {
      set({ error: (err as Error).message });
    }
  },

  loadSessionNames: async () => {
    try {
      const names = await api.sessions.getAllNames();
      set({ customSessionNames: names });
    } catch {
      // Non-critical, keep empty
    }
  },

  setSessionName: (sessionId, name) => {
    set((s) => {
      const names = { ...s.customSessionNames };
      if (name) {
        names[sessionId] = name;
      } else {
        delete names[sessionId];
      }
      return { customSessionNames: names };
    });
    // Persist to backend (fire-and-forget)
    api.sessions.setName(sessionId, name).catch(() => {});
  },

  setSessionState: (sessionId, state) => {
    set((s) => ({
      sessionStates: { ...s.sessionStates, [sessionId]: state },
    }));
  },

  setRepositories: (repos) => {
    set({ repositories: repos });
    useNotificationsStore.getState().syncFromRepositories(repos);
  },
}));
