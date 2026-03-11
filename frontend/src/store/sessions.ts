import { create } from 'zustand';
import type { CLISession, SelectedRepository, SessionMonitorState, SessionHistoryEntry, WorktreeBranch } from '@/types/generated';
import { api, createApiForHost } from '@/api/client';
import { useNotificationsStore } from '@/store/notifications';
import { LOCALHOST_HOST_ID } from '@/types/hosts';
import { SessionId } from '@/types/session';
import { useHostsStore } from '@/store/hosts';

type Provider = string;

/** Lightweight pub/sub for streaming history entries from WS to SessionHistoryView. */
type HistoryAppendListener = (
  sessionId: SessionId,
  entries: SessionHistoryEntry[],
  totalLines: number,
) => void;

class HistoryAppendBus {
  private listeners = new Set<HistoryAppendListener>();

  subscribe(listener: HistoryAppendListener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  notify(sessionId: SessionId, entries: SessionHistoryEntry[], totalLines: number) {
    for (const listener of this.listeners) {
      listener(sessionId, entries, totalLines);
    }
  }
}

export const historyAppendBus = new HistoryAppendBus();

/** A session whose `id` has been scoped to its host via {@link SessionId}. */
export interface TaggedSession extends Omit<CLISession, 'id'> {
  id: SessionId;
}

/** A worktree branch whose sessions have been tagged with a host-scoped ID. */
export interface TaggedWorktreeBranch extends Omit<WorktreeBranch, 'sessions'> {
  sessions?: TaggedSession[];
}

/** Repository annotated with which host it lives on; sessions carry {@link SessionId}s. */
export interface HostedRepository extends Omit<SelectedRepository, 'worktrees'> {
  host_id: string;
  worktrees?: TaggedWorktreeBranch[];
}

interface SessionsState {
  /** Repository tree (repos → worktrees → sessions), annotated with host_id. */
  repositories: HostedRepository[];
  /** Per-host repository lists — merged into `repositories`. */
  _reposByHost: Record<string, HostedRepository[]>;
  /** Session states keyed by session ID (from WS session_state_update). */
  sessionStates: Record<string, SessionMonitorState>;
  /** Session IDs currently being monitored. */
  monitoredSessionIds: Set<SessionId>;
  /** Subscription info for monitored sessions. */
  monitoredSessionInfo: Record<string, { projectPath: string; sessionFilePath: string; hostId: string }>;

  selectedSessionId: SessionId | null;
  selectedRepositoryPath: string | null;
  activeProvider: Provider;
  loading: boolean;
  error: string | null;
  /** User-assigned custom names for sessions (session_id -> name). */
  customSessionNames: Record<string, string>;
  /** Session ID to reveal/focus in the sidebar tree (cleared after handling). */
  revealSessionId: SessionId | null;

  // Actions
  fetchRepositories: (provider?: Provider) => Promise<void>;
  fetchAllRepositories: (provider?: Provider) => Promise<void>;
  addRepository: (path: string, provider?: Provider, hostId?: string) => Promise<void>;
  removeRepository: (path: string, provider?: Provider) => Promise<void>;
  selectRepository: (path: string | null) => void;
  selectSession: (id: SessionId | null) => void;
  setActiveProvider: (provider: Provider) => void;
  refreshSessions: () => Promise<void>;
  revealSession: (id: SessionId) => void;
  clearReveal: () => void;
  startMonitoring: (
    sessionId: SessionId,
    projectPath: string,
    sessionFilePath?: string,
  ) => Promise<void>;
  stopMonitoring: (sessionId: SessionId) => Promise<void>;
  refreshSessionState: (sessionId: SessionId) => Promise<void>;

  /** Load persisted custom names from backend. */
  loadSessionNames: () => Promise<void>;
  /** Set or clear a custom name for a session (persists to backend). */
  setSessionName: (sessionId: SessionId, name: string | null) => void;

  /** Called by WS hook when session_state_update arrives. */
  setSessionState: (sessionId: SessionId, state: SessionMonitorState) => void;
  /** Called by WS hook when sessions_updated arrives (legacy — routes to setHostRepositories). */
  setRepositories: (repos: SelectedRepository[]) => void;
  /** Called by WS hook when sessions_updated arrives for a specific host. */
  setHostRepositories: (hostId: string, repos: SelectedRepository[]) => void;
}

export const useSessionsStore = create<SessionsState>((set, get) => ({
  repositories: [],
  _reposByHost: {},
  sessionStates: {},
  monitoredSessionIds: new Set<SessionId>(),
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
      const repos = await api.repositories.list(provider ?? get().activeProvider);
      const tagged: HostedRepository[] = repos.map((r) => ({
        ...r,
        host_id: LOCALHOST_HOST_ID,
        worktrees: (r.worktrees ?? []).map((wt): TaggedWorktreeBranch => ({
          ...wt,
          sessions: (wt.sessions ?? []).map((s): TaggedSession => ({
            ...s,
            id: SessionId.wrap(s.id, 0),
          })),
        })),
      }));
      const reposByHost = { ...get()._reposByHost, [LOCALHOST_HOST_ID]: tagged };
      const merged = (Object.values(reposByHost) as HostedRepository[][]).flat();
      set({ repositories: merged, _reposByHost: reposByHost, loading: false });
      useNotificationsStore.getState().syncFromRepositories(merged);
    } catch (err) {
      set({ error: (err as Error).message, loading: false });
    }
  },

  fetchAllRepositories: async (provider) => {
    set({ loading: true, error: null });
    try {
      const prov = provider ?? get().activeProvider;
      const localRepos = await api.repositories.list(prov);
      const tagged: HostedRepository[] = localRepos.map((r) => ({
        ...r,
        host_id: LOCALHOST_HOST_ID,
        worktrees: (r.worktrees ?? []).map((wt): TaggedWorktreeBranch => ({
          ...wt,
          sessions: (wt.sessions ?? []).map((s): TaggedSession => ({
            ...s,
            id: SessionId.wrap(s.id, 0),
          })),
        })),
      }));
      const reposByHost: Record<string, HostedRepository[]> = { [LOCALHOST_HOST_ID]: tagged };

      // Fetch from each connected remote host
      const hostsState = useHostsStore.getState();
      for (const host of hostsState.hosts) {
        if (!hostsState.isConnected(host.id)) continue;
        try {
          const remoteRepos = await createApiForHost(host.id).repositories.list(prov);
          reposByHost[host.id] = remoteRepos.map((r) => ({
            ...r,
            host_id: host.id,
            worktrees: (r.worktrees ?? []).map((wt): TaggedWorktreeBranch => ({
              ...wt,
              sessions: (wt.sessions ?? []).map((s): TaggedSession => ({
                ...s,
                id: SessionId.wrap(s.id, host.hostSeq),
              })),
            })),
          }));
        } catch {
          // Remote fetch failed — keep existing repos for that host
          if (get()._reposByHost[host.id]) {
            reposByHost[host.id] = get()._reposByHost[host.id] ?? [];
          }
        }
      }

      const merged = (Object.values(reposByHost) as HostedRepository[][]).flat();
      set({ repositories: merged, _reposByHost: reposByHost, loading: false });
      useNotificationsStore.getState().syncFromRepositories(merged);
    } catch (err) {
      set({ error: (err as Error).message, loading: false });
    }
  },

  addRepository: async (path, provider, hostId = LOCALHOST_HOST_ID) => {
    set({ loading: true, error: null });
    try {
      const apiClient = hostId === LOCALHOST_HOST_ID ? api : createApiForHost(hostId);
      await apiClient.repositories.add(path, provider ?? get().activeProvider);
      await get().fetchAllRepositories(provider);
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
      // Find the host for this session
      const repo = get().repositories.find((r) =>
        (r.worktrees ?? []).some((wt) =>
          (wt.sessions ?? []).some((s) => s.id === sessionId),
        ),
      );
      const hostId = (repo as HostedRepository | undefined)?.host_id ?? LOCALHOST_HOST_ID;
      const apiClient = hostId === LOCALHOST_HOST_ID ? api : createApiForHost(hostId);

      // Pass the full SessionId — the API client extracts rawId internally
      const resp = await apiClient.sessions.startMonitoring(
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
        info[sessionId] = { projectPath, sessionFilePath: sessionFilePath ?? '', hostId };
        return { monitoredSessionIds: ids, sessionStates: states, monitoredSessionInfo: info };
      });
    } catch (err) {
      set({ error: (err as Error).message });
    }
  },

  stopMonitoring: async (sessionId) => {
    set({ error: null });
    try {
      const hostId = get().monitoredSessionInfo[sessionId]?.hostId ?? LOCALHOST_HOST_ID;
      const apiClient = hostId === LOCALHOST_HOST_ID ? api : createApiForHost(hostId);
      await apiClient.sessions.stopMonitoring(sessionId, get().activeProvider);
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
      const hostId = get().monitoredSessionInfo[sessionId]?.hostId ?? LOCALHOST_HOST_ID;
      const apiClient = hostId === LOCALHOST_HOST_ID ? api : createApiForHost(hostId);
      const state = await apiClient.sessions.refreshState(sessionId, get().activeProvider);
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
    // Persist to backend (fire-and-forget) — route to the correct host
    const hostId = get().repositories
      .find((r) => (r.worktrees ?? []).some((wt) => (wt.sessions ?? []).some((s) => s.id === sessionId)))
      ?.host_id ?? LOCALHOST_HOST_ID;
    const apiClient = hostId === LOCALHOST_HOST_ID ? api : createApiForHost(hostId);
    apiClient.sessions.setName(sessionId, name).catch(() => {});
  },

  setSessionState: (sessionId, state) => {
    set((s) => ({
      sessionStates: { ...s.sessionStates, [sessionId]: state },
    }));
  },

  setRepositories: (repos) => {
    // Legacy: treat as localhost update
    get().setHostRepositories(LOCALHOST_HOST_ID, repos);
  },

  setHostRepositories: (hostId, repos) => {
    const hostSeq = hostId === LOCALHOST_HOST_ID
      ? 0
      : (useHostsStore.getState().hosts.find((h) => h.id === hostId)?.hostSeq ?? 0);
    const tagged: HostedRepository[] = repos.map((r) => ({
      ...r,
      host_id: hostId,
      worktrees: (r.worktrees ?? []).map((wt): TaggedWorktreeBranch => ({
        ...wt,
        sessions: (wt.sessions ?? []).map((s): TaggedSession => ({
          ...s,
          id: SessionId.wrap(s.id, hostSeq),
        })),
      })),
    }));
    set((s) => {
      const reposByHost = { ...s._reposByHost, [hostId]: tagged };
      const merged = (Object.values(reposByHost) as HostedRepository[][]).flat();
      useNotificationsStore.getState().syncFromRepositories(merged);
      return { repositories: merged, _reposByHost: reposByHost };
    });
  },
}));
