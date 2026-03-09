/**
 * REST API client for AgentHub backend.
 *
 * All endpoints return unwrapped data — callers get the inner types
 * directly, not the wrapper objects the backend sends.
 */

import type {
  CLISession,
  DiffMode,
  GitDiffFileEntry,
  GitDiffState,
  GlobalStatsCache,
  ParsedFileDiff,
  RemoteBranch,
  SelectedRepository,
  SessionMonitorState,
  SessionSearchResult,
} from '@/types/generated';

// ---------------------------------------------------------------------------
// Base fetch helpers
// ---------------------------------------------------------------------------

const API_BASE = '/api';

// ---------------------------------------------------------------------------
// Per-host API base — remote hosts are proxied through the local backend
// ---------------------------------------------------------------------------

/**
 * Return the API base path for a given host.
 *
 * - ``__local__`` (localhost) → ``/api``
 * - any remote host id       → ``/api/hosts/{id}/proxy/api``
 */
export function apiBaseForHost(hostId: string): string {
  if (hostId === '__local__') return API_BASE;
  return `${API_BASE}/hosts/${encodeURIComponent(hostId)}/proxy/api`;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public statusText: string,
    public body: unknown,
  ) {
    super(`API Error ${status}: ${statusText}`);
    this.name = 'ApiError';
  }
}

async function fetchApi<T>(
  path: string,
  options: RequestInit = {},
  base: string = API_BASE,
): Promise<T> {
  const url = `${base}${path}`;
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string> | undefined),
  };

  const response = await fetch(url, { ...options, headers });

  if (!response.ok) {
    let body: unknown;
    try {
      body = await response.json();
    } catch {
      body = await response.text().catch(() => null);
    }
    throw new ApiError(response.status, response.statusText, body);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return response.json() as Promise<T>;
}

function get<T>(path: string, base?: string): Promise<T> {
  return fetchApi<T>(path, { method: 'GET' }, base);
}

function post<T>(path: string, body?: unknown, base?: string): Promise<T> {
  return fetchApi<T>(
    path,
    { method: 'POST', body: body !== undefined ? JSON.stringify(body) : undefined },
    base,
  );
}

function put<T>(path: string, body?: unknown, base?: string): Promise<T> {
  return fetchApi<T>(
    path,
    { method: 'PUT', body: body !== undefined ? JSON.stringify(body) : undefined },
    base,
  );
}

function del<T = void>(path: string, body?: unknown, base?: string): Promise<T> {
  return fetchApi<T>(
    path,
    { method: 'DELETE', body: body !== undefined ? JSON.stringify(body) : undefined },
    base,
  );
}

// ---------------------------------------------------------------------------
// Query-string helper
// ---------------------------------------------------------------------------

function qs(params: Record<string, string | number | boolean | undefined | null>): string {
  const parts: string[] = [];
  for (const [k, v] of Object.entries(params)) {
    if (v != null && v !== '') parts.push(`${k}=${encodeURIComponent(String(v))}`);
  }
  return parts.length ? `?${parts.join('&')}` : '';
}

// ---------------------------------------------------------------------------
// Backend response wrapper interfaces (not exported — internal only)
// ---------------------------------------------------------------------------

interface RepoListResp {
  repositories: SelectedRepository[];
  total: number;
}
interface RepoAddResp {
  repository: SelectedRepository | null;
  already_exists: boolean;
}
interface SessionListResp {
  sessions: CLISession[];
  total: number;
}
interface SessionGetResp {
  session: CLISession;
  repository_path: string;
  provider: string;
}
interface MonitorStateResp {
  session_id: string;
  state: SessionMonitorState | null;
  monitoring: boolean;
}
interface StatsResp {
  provider: string;
  stats: GlobalStatsCache | null;
}
interface SearchResp {
  query: string;
  results: SessionSearchResult[];
  total: number;
}
interface HistoryEntryResp {
  line: number;
  type: string;
  data: Record<string, unknown>;
}
interface SessionHistoryResp {
  session_id: string;
  entries: HistoryEntryResp[];
  total_lines: number;
  offset: number;
  has_more: boolean;
}
interface SettingsResp {
  settings: Record<string, unknown>;
}
interface SettingsUpdateResp {
  success: boolean;
  settings: Record<string, unknown>;
}
interface CLIStatusEntry {
  key: string;
  label: string;
  color: string;
  available: boolean;
  path: string | null;
}
interface CLIStatusResp {
  providers: CLIStatusEntry[];
}
interface DiffResp {
  repo_path: string;
  mode: DiffMode;
  base_branch: string | null;
  diff: GitDiffState & { file_count: number };
}
interface UnifiedDiffResp {
  repo_path: string;
  mode: DiffMode;
  diff_text: string;
}
interface BranchListResp {
  branches: RemoteBranch[];
  total: number;
}
interface TerminalLaunchResp {
  key: string;
  pid: number;
  fd: number;
  session_id: string | null;
  project_path: string;
}
interface TerminalListResp {
  terminals: TerminalLaunchResp[];
  total: number;
}
interface GitRootResp {
  path: string;
  git_root: string;
}

// ---------------------------------------------------------------------------
// Host connect/disconnect request types (frontend-defined, not generated)
// ---------------------------------------------------------------------------

interface HostConnectReq {
  id: string;
  label: string;
  kind: 'direct' | 'ssh';
  base_url: string;
  ssh_host: string;
  ssh_port: number;
  ssh_user: string;
  ssh_password: string;
  ssh_key: string;
  remote_port: number;
}
interface HostConnectResp { host_id: string; connected: boolean }
interface ConnectedHostsResp { host_ids: string[] }

// ---------------------------------------------------------------------------
// API builder — parameterised by base path so the same shape works for
// both localhost (/api) and proxied remote hosts (/api/hosts/{id}/proxy/api)
// ---------------------------------------------------------------------------

function buildApiClient(base: string) {
  const g = <T>(path: string) => get<T>(path, base);
  const p = <T>(path: string, body?: unknown) => post<T>(path, body, base);
  const pu = <T>(path: string, body?: unknown) => put<T>(path, body, base);
  const d = <T = void>(path: string, body?: unknown) => del<T>(path, body, base);

  return {
    repositories: {
      list: async (provider = 'claude'): Promise<SelectedRepository[]> => {
        const r = await g<RepoListResp>(`/repositories${qs({ provider })}`);
        return r.repositories ?? [];
      },
      add: async (path: string, provider = 'claude'): Promise<RepoAddResp> =>
        p<RepoAddResp>('/repositories', { path, provider }),
      remove: async (path: string, provider = 'claude'): Promise<void> => {
        await d(`/repositories/${encodeURIComponent(path)}${qs({ provider })}`);
      },
      refresh: async (_provider?: string): Promise<void> => {
        await p('/repositories/refresh', undefined);
      },
    },

    sessions: {
      list: async (provider = 'claude'): Promise<CLISession[]> => {
        const r = await g<SessionListResp>(`/sessions${qs({ provider })}`);
        return r.sessions ?? [];
      },
      get: async (id: string, provider = 'claude'): Promise<SessionGetResp> =>
        g<SessionGetResp>(`/sessions/${encodeURIComponent(id)}${qs({ provider })}`),
      getState: async (id: string, provider = 'claude'): Promise<SessionMonitorState | null> => {
        const r = await g<MonitorStateResp>(
          `/sessions/${encodeURIComponent(id)}/state${qs({ provider })}`,
        );
        return r.state ?? null;
      },
      startMonitoring: async (
        id: string,
        projectPath: string,
        sessionFilePath?: string,
        provider = 'claude',
      ): Promise<MonitorStateResp> =>
        p<MonitorStateResp>(`/sessions/${encodeURIComponent(id)}/monitor`, {
          project_path: projectPath,
          session_file_path: sessionFilePath,
          provider,
        }),
      stopMonitoring: async (id: string, provider = 'claude'): Promise<void> => {
        await d(`/sessions/${encodeURIComponent(id)}/monitor${qs({ provider })}`);
      },
      refreshState: async (id: string, provider = 'claude'): Promise<SessionMonitorState | null> => {
        const r = await p<MonitorStateResp>(
          `/sessions/${encodeURIComponent(id)}/refresh${qs({ provider })}`,
        );
        return r.state ?? null;
      },
      refreshAll: async (provider?: string): Promise<void> => {
        await p(`/repositories/refresh${qs({ provider: provider ?? '' })}`);
      },
      getAllNames: async (): Promise<Record<string, string>> => {
        const r = await g<{ names: Record<string, string> }>('/sessions/names/all');
        return r.names ?? {};
      },
      setName: async (sessionId: string, name: string | null): Promise<void> => {
        await pu(`/sessions/${encodeURIComponent(sessionId)}/name`, { name });
      },
      history: async (
        sessionId: string,
        offset = 0,
        limit = 50,
      ): Promise<SessionHistoryResp> =>
        g<SessionHistoryResp>(
          `/sessions/${encodeURIComponent(sessionId)}/history${qs({ offset, limit })}`,
        ),
      plan: async (
        sessionId: string,
      ): Promise<{ plan_file_path: string | null; plan_content: string | null }> =>
        g<{ session_id: string; plan_file_path: string | null; plan_content: string | null }>(
          `/sessions/${encodeURIComponent(sessionId)}/plan`,
        ),
    },

    git: {
      diff: async (
        repoPath: string,
        mode: DiffMode = 'unstaged',
        baseBranch?: string,
        filePath?: string,
      ): Promise<GitDiffFileEntry[]> => {
        const r = await g<DiffResp>(
          `/git/diff${qs({ repo_path: repoPath, mode, base_branch: baseBranch, file_path: filePath })}`,
        );
        return r.diff?.files ?? [];
      },
      unifiedDiff: async (
        repoPath: string,
        mode: DiffMode = 'unstaged',
        baseBranch?: string,
      ): Promise<string> => {
        const r = await g<UnifiedDiffResp>(
          `/git/diff/unified${qs({ repo_path: repoPath, mode, base_branch: baseBranch })}`,
        );
        return r.diff_text ?? '';
      },
      fileDiff: async (
        filePath: string,
        repoPath: string,
        mode: DiffMode = 'unstaged',
        baseBranch?: string,
      ): Promise<ParsedFileDiff> =>
        g<ParsedFileDiff>(
          `/git/diff/file${qs({ file_path: filePath, repo_path: repoPath, mode, base_branch: baseBranch })}`,
        ),
      remoteBranches: async (repoPath: string, fetchRemotes = false): Promise<RemoteBranch[]> => {
        const r = await g<BranchListResp>(
          `/git/branches/remote${qs({ repo_path: repoPath, fetch: fetchRemotes })}`,
        );
        return r.branches ?? [];
      },
      localBranches: async (repoPath: string): Promise<RemoteBranch[]> => {
        const r = await g<BranchListResp>(`/git/branches/local${qs({ repo_path: repoPath })}`);
        return r.branches ?? [];
      },
      createWorktree: (
        repoPath: string,
        branch: string,
        newBranch = false,
        startPoint?: string,
      ) =>
        p<{ worktree_path: string; branch: string; success: boolean }>('/git/worktree', {
          repo_path: repoPath,
          branch,
          new_branch: newBranch,
          start_point: startPoint,
        }),
      deleteWorktree: (worktreePath: string, force = false) =>
        d<{ success: boolean; message: string }>('/git/worktree', {
          worktree_path: worktreePath,
          force,
        }),
      root: async (path: string): Promise<string> => {
        const r = await g<GitRootResp>(`/git/root${qs({ path })}`);
        return r.git_root;
      },
    },

    search: {
      query: async (
        q: string,
        provider = 'claude',
        filterPath?: string,
      ): Promise<SessionSearchResult[]> => {
        const r = await g<SearchResp>(`/search${qs({ q, provider, filter_path: filterPath })}`);
        return r.results ?? [];
      },
      reindex: (provider?: string) =>
        p<{ success: boolean; indexed_count: number; message: string }>(
          `/search/reindex${qs({ provider })}`,
        ),
    },

    stats: {
      get: async (provider = 'claude'): Promise<GlobalStatsCache | null> => {
        const r = await g<StatsResp>(`/stats/${provider}`);
        return r.stats ?? null;
      },
      refresh: (provider: string) =>
        p<{ provider: string; success: boolean; message: string }>(`/stats/${provider}/refresh`),
    },

    settings: {
      get: async (): Promise<Record<string, unknown>> => {
        const r = await g<SettingsResp>('/settings');
        return r.settings ?? {};
      },
      update: async (settings: Record<string, unknown>): Promise<Record<string, unknown>> => {
        const r = await pu<SettingsUpdateResp>('/settings', settings);
        return r.settings ?? {};
      },
      cliStatus: async (): Promise<CLIStatusEntry[]> => {
        const r = await g<CLIStatusResp>('/settings/cli-status');
        return r.providers ?? [];
      },
    },

    terminal: {
      launch: (opts: {
        command?: string;
        project_path?: string;
        session_id?: string;
        resume?: boolean;
        prompt?: string;
      }) => p<TerminalLaunchResp>('/terminal/launch', opts),
      resize: (key: string, rows: number, cols: number) =>
        p<{ key: string; success: boolean }>(`/terminal/${encodeURIComponent(key)}/resize`, {
          rows,
          cols,
        }),
      kill: (key: string) => d<{ key: string; terminated: boolean }>(
        `/terminal/${encodeURIComponent(key)}`,
      ),
      list: async (): Promise<TerminalLaunchResp[]> => {
        const r = await g<TerminalListResp>('/terminal');
        return r.terminals ?? [];
      },
    },
  };
}

/** Return an API client that routes through the proxy for a remote host. */
export function createApiForHost(hostId: string): ReturnType<typeof buildApiClient> {
  return buildApiClient(apiBaseForHost(hostId));
}

// ---------------------------------------------------------------------------
// Typed, unwrapped API surface
// ---------------------------------------------------------------------------

export const api = {
  ...buildApiClient(API_BASE),

  // ---- Hosts (local-backend-only — not proxied) ----
  hosts: {
    connect: (req: HostConnectReq): Promise<HostConnectResp> =>
      post<HostConnectResp>('/hosts/connect', req),
    disconnect: (hostId: string): Promise<void> =>
      post(`/hosts/${encodeURIComponent(hostId)}/disconnect`),
    listConnected: async (): Promise<string[]> => {
      const r = await get<ConnectedHostsResp>('/hosts/connected');
      return r.host_ids ?? [];
    },
  },
};
