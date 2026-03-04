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

async function fetchApi<T>(path: string, options: RequestInit = {}): Promise<T> {
  const url = `${API_BASE}${path}`;
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

function get<T>(path: string): Promise<T> {
  return fetchApi<T>(path, { method: 'GET' });
}

function post<T>(path: string, body?: unknown): Promise<T> {
  return fetchApi<T>(path, {
    method: 'POST',
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
}

function put<T>(path: string, body?: unknown): Promise<T> {
  return fetchApi<T>(path, {
    method: 'PUT',
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
}

function del<T = void>(path: string, body?: unknown): Promise<T> {
  return fetchApi<T>(path, {
    method: 'DELETE',
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
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
// Typed, unwrapped API surface
// ---------------------------------------------------------------------------

export const api = {
  // ---- Repositories ----
  repositories: {
    list: async (provider = 'claude'): Promise<SelectedRepository[]> => {
      const r = await get<RepoListResp>(`/repositories${qs({ provider })}`);
      return r.repositories ?? [];
    },
    add: async (path: string, provider = 'claude'): Promise<RepoAddResp> =>
      post<RepoAddResp>('/repositories', { path, provider }),
    remove: async (path: string, provider = 'claude'): Promise<void> => {
      await del(`/repositories/${encodeURIComponent(path)}${qs({ provider })}`);
    },
    refresh: async (provider?: string): Promise<void> => {
      await post('/repositories/refresh', undefined);
    },
  },

  // ---- Sessions ----
  sessions: {
    list: async (provider = 'claude'): Promise<CLISession[]> => {
      const r = await get<SessionListResp>(`/sessions${qs({ provider })}`);
      return r.sessions ?? [];
    },
    get: async (id: string, provider = 'claude'): Promise<SessionGetResp> =>
      get<SessionGetResp>(`/sessions/${encodeURIComponent(id)}${qs({ provider })}`),
    getState: async (
      id: string,
      provider = 'claude',
    ): Promise<SessionMonitorState | null> => {
      const r = await get<MonitorStateResp>(
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
      post<MonitorStateResp>(`/sessions/${encodeURIComponent(id)}/monitor`, {
        project_path: projectPath,
        session_file_path: sessionFilePath,
        provider,
      }),
    stopMonitoring: async (id: string, provider = 'claude'): Promise<void> => {
      await del(`/sessions/${encodeURIComponent(id)}/monitor${qs({ provider })}`);
    },
    refreshState: async (id: string, provider = 'claude'): Promise<SessionMonitorState | null> => {
      const r = await post<MonitorStateResp>(
        `/sessions/${encodeURIComponent(id)}/refresh${qs({ provider })}`,
      );
      return r.state ?? null;
    },
    refreshAll: async (provider?: string): Promise<void> => {
      await post(`/repositories/refresh${qs({ provider: provider ?? '' })}`);
    },
    getAllNames: async (): Promise<Record<string, string>> => {
      const r = await get<{ names: Record<string, string> }>('/sessions/names/all');
      return r.names ?? {};
    },
    setName: async (sessionId: string, name: string | null): Promise<void> => {
      await put(`/sessions/${encodeURIComponent(sessionId)}/name`, { name });
    },
    history: async (
      sessionId: string,
      offset = 0,
      limit = 50,
    ): Promise<SessionHistoryResp> =>
      get<SessionHistoryResp>(
        `/sessions/${encodeURIComponent(sessionId)}/history${qs({ offset, limit })}`,
      ),
    plan: async (sessionId: string): Promise<{ plan_file_path: string | null; plan_content: string | null }> =>
      get<{ session_id: string; plan_file_path: string | null; plan_content: string | null }>(
        `/sessions/${encodeURIComponent(sessionId)}/plan`,
      ),
  },

  // ---- Git ----
  git: {
    diff: async (
      repoPath: string,
      mode: DiffMode = 'unstaged',
      baseBranch?: string,
      filePath?: string,
    ): Promise<GitDiffFileEntry[]> => {
      const r = await get<DiffResp>(
        `/git/diff${qs({ repo_path: repoPath, mode, base_branch: baseBranch, file_path: filePath })}`,
      );
      return r.diff?.files ?? [];
    },
    unifiedDiff: async (
      repoPath: string,
      mode: DiffMode = 'unstaged',
      baseBranch?: string,
    ): Promise<string> => {
      const r = await get<UnifiedDiffResp>(
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
      get<ParsedFileDiff>(
        `/git/diff/file${qs({ file_path: filePath, repo_path: repoPath, mode, base_branch: baseBranch })}`,
      ),
    remoteBranches: async (repoPath: string, fetchRemotes = false): Promise<RemoteBranch[]> => {
      const r = await get<BranchListResp>(
        `/git/branches/remote${qs({ repo_path: repoPath, fetch: fetchRemotes })}`,
      );
      return r.branches ?? [];
    },
    localBranches: async (repoPath: string): Promise<RemoteBranch[]> => {
      const r = await get<BranchListResp>(
        `/git/branches/local${qs({ repo_path: repoPath })}`,
      );
      return r.branches ?? [];
    },
    createWorktree: (
      repoPath: string,
      branch: string,
      newBranch = false,
      startPoint?: string,
    ) =>
      post<{ worktree_path: string; branch: string; success: boolean }>(
        '/git/worktree',
        { repo_path: repoPath, branch, new_branch: newBranch, start_point: startPoint },
      ),
    deleteWorktree: (worktreePath: string, force = false) =>
      del<{ success: boolean; message: string }>(
        '/git/worktree',
        { worktree_path: worktreePath, force },
      ),
    root: async (path: string): Promise<string> => {
      const r = await get<GitRootResp>(`/git/root${qs({ path })}`);
      return r.git_root;
    },
  },

  // ---- Search ----
  search: {
    query: async (
      q: string,
      provider = 'claude',
      filterPath?: string,
    ): Promise<SessionSearchResult[]> => {
      const r = await get<SearchResp>(
        `/search${qs({ q, provider, filter_path: filterPath })}`,
      );
      return r.results ?? [];
    },
    reindex: (provider?: string) =>
      post<{ success: boolean; indexed_count: number; message: string }>(
        `/search/reindex${qs({ provider })}`,
      ),
  },

  // ---- Stats ----
  stats: {
    get: async (provider = 'claude'): Promise<GlobalStatsCache | null> => {
      const r = await get<StatsResp>(`/stats/${provider}`);
      return r.stats ?? null;
    },
    refresh: (provider: string) =>
      post<{ provider: string; success: boolean; message: string }>(
        `/stats/${provider}/refresh`,
      ),
  },

  // ---- Settings ----
  settings: {
    get: async (): Promise<Record<string, unknown>> => {
      const r = await get<SettingsResp>('/settings');
      return r.settings ?? {};
    },
    update: async (settings: Record<string, unknown>): Promise<Record<string, unknown>> => {
      const r = await put<SettingsUpdateResp>('/settings', settings);
      return r.settings ?? {};
    },
    cliStatus: async (): Promise<CLIStatusEntry[]> => {
      const r = await get<CLIStatusResp>('/settings/cli-status');
      return r.providers ?? [];
    },
  },

  // ---- Terminal ----
  terminal: {
    launch: (opts: {
      command?: string;
      project_path?: string;
      session_id?: string;
      resume?: boolean;
      prompt?: string;
    }) => post<TerminalLaunchResp>('/terminal/launch', opts),
    resize: (key: string, rows: number, cols: number) =>
      post<{ key: string; success: boolean }>(`/terminal/${encodeURIComponent(key)}/resize`, {
        rows,
        cols,
      }),
    kill: (key: string) => del<{ key: string; terminated: boolean }>(
      `/terminal/${encodeURIComponent(key)}`,
    ),
    list: async (): Promise<TerminalLaunchResp[]> => {
      const r = await get<TerminalListResp>('/terminal');
      return r.terminals ?? [];
    },
  },
};
