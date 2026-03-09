import React, { useState, useCallback, useEffect } from 'react';
import type { SelectedRepository, WorktreeBranch, CLISession } from '@/types/generated';
import { useSessionsStore, type HostedRepository } from '@/store/sessions';
import { useHostsStore, type ConnectionStatus } from '@/store/hosts';
import { LOCALHOST_HOST_ID } from '@/types/hosts';
import { api } from '@/api/client';
import { SessionRow } from './SessionRow';

/**
 * Count all sessions across every worktree in a repository.
 */
function countSessions(repo: SelectedRepository): number {
  return (repo.worktrees ?? []).reduce(
    (sum, wt) => sum + (wt.sessions?.length ?? 0),
    0,
  );
}

/**
 * Count active sessions across every worktree in a repository.
 */
function countActiveSessions(repo: SelectedRepository): number {
  return (repo.worktrees ?? []).reduce(
    (sum, wt) =>
      sum + (wt.sessions ?? []).filter((s) => s.is_active).length,
    0,
  );
}

interface RepositoryTreeViewProps {
  filter?: string;
}

export const RepositoryTreeView: React.FC<RepositoryTreeViewProps> = ({ filter }) => {
  const repositories = useSessionsStore((s) => s.repositories);
  const selectedSessionId = useSessionsStore((s) => s.selectedSessionId);
  const selectedRepositoryPath = useSessionsStore((s) => s.selectedRepositoryPath);
  const sessionStates = useSessionsStore((s) => s.sessionStates);
  const monitoredSessionIds = useSessionsStore((s) => s.monitoredSessionIds);
  const selectSession = useSessionsStore((s) => s.selectSession);
  const selectRepository = useSessionsStore((s) => s.selectRepository);
  const startMonitoring = useSessionsStore((s) => s.startMonitoring);
  const removeRepository = useSessionsStore((s) => s.removeRepository);
  const fetchRepositories = useSessionsStore((s) => s.fetchRepositories);
  const revealSessionId = useSessionsStore((s) => s.revealSessionId);
  const clearReveal = useSessionsStore((s) => s.clearReveal);
  const hosts = useHostsStore((s) => s.hosts);
  const runtimeState = useHostsStore((s) => s.runtimeState);
  const connectHost = useHostsStore((s) => s.connectHost);
  const disconnectHost = useHostsStore((s) => s.disconnectHost);

  // Local expansion state for repos and worktrees.
  const [expandedRepos, setExpandedRepos] = useState<Set<string>>(
    () => new Set(repositories.map((r) => r.path)),
  );
  const [expandedWorktrees, setExpandedWorktrees] = useState<Set<string>>(
    () => {
      const keys = new Set<string>();
      for (const repo of repositories) {
        for (const wt of repo.worktrees ?? []) {
          keys.add(`${repo.path}::${wt.path}`);
        }
      }
      return keys;
    },
  );

  const toggleRepo = useCallback((repoPath: string) => {
    setExpandedRepos((prev) => {
      const next = new Set(prev);
      if (next.has(repoPath)) {
        next.delete(repoPath);
      } else {
        next.add(repoPath);
      }
      return next;
    });
  }, []);

  const toggleWorktree = useCallback((key: string) => {
    setExpandedWorktrees((prev) => {
      const next = new Set(prev);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  }, []);

  // Reveal: expand the containing repo+worktree and scroll the session row into view
  useEffect(() => {
    if (!revealSessionId) return;
    for (const repo of repositories) {
      for (const wt of repo.worktrees ?? []) {
        if ((wt.sessions ?? []).some((s) => s.id === revealSessionId)) {
          setExpandedRepos((prev) => {
            const next = new Set(prev);
            next.add(repo.path);
            return next;
          });
          setExpandedWorktrees((prev) => {
            const next = new Set(prev);
            next.add(`${repo.path}::${wt.path}`);
            return next;
          });
          // Scroll after state updates flush
          setTimeout(() => {
            document.querySelector(`[data-session-id="${revealSessionId}"]`)
              ?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
          }, 50);
          break;
        }
      }
    }
    clearReveal();
  }, [revealSessionId, repositories, clearReveal]);

  const handleSessionClick = useCallback(
    (session: CLISession) => {
      selectSession(session.id);
    },
    [selectSession],
  );

  const handleSessionDoubleClick = useCallback(
    (session: CLISession) => {
      startMonitoring(session.id, session.project_path, session.session_file_path);
    },
    [startMonitoring],
  );

  const handleRemoveRepo = useCallback(
    (e: React.MouseEvent, repoPath: string) => {
      e.stopPropagation();
      removeRepository(repoPath);
    },
    [removeRepository],
  );

  const handleDeleteWorktree = useCallback(
    async (e: React.MouseEvent, worktreePath: string) => {
      e.stopPropagation();
      try {
        await api.git.deleteWorktree(worktreePath);
        await fetchRepositories();
      } catch {
        // Silently fail — could add error toast later
      }
    },
    [fetchRepositories],
  );

  const handleStartSession = useCallback(
    async (e: React.MouseEvent, projectPath: string) => {
      e.stopPropagation();
      try {
        await api.terminal.launch({
          command: 'claude',
          project_path: projectPath,
        });
      } catch {
        // Silently fail
      }
    },
    [],
  );

  // Apply text filter across repo names, worktree names, and session slugs/messages
  const lowerFilter = filter?.toLowerCase() ?? '';

  function sessionMatchesFilter(session: CLISession): boolean {
    if (!lowerFilter) return true;
    return (
      (session.slug?.toLowerCase().includes(lowerFilter) ?? false) ||
      session.id.toLowerCase().includes(lowerFilter) ||
      (session.first_message?.toLowerCase().includes(lowerFilter) ?? false) ||
      (session.branch_name?.toLowerCase().includes(lowerFilter) ?? false)
    );
  }

  function worktreeMatchesFilter(wt: WorktreeBranch): boolean {
    if (!lowerFilter) return true;
    if (wt.name.toLowerCase().includes(lowerFilter)) return true;
    return (wt.sessions ?? []).some(sessionMatchesFilter);
  }

  function repoMatchesFilter(repo: SelectedRepository): boolean {
    if (!lowerFilter) return true;
    if (repo.name.toLowerCase().includes(lowerFilter)) return true;
    if (repo.path.toLowerCase().includes(lowerFilter)) return true;
    return (repo.worktrees ?? []).some(worktreeMatchesFilter);
  }

  const filteredRepos = (lowerFilter
    ? repositories.filter(repoMatchesFilter)
    : repositories) as HostedRepository[];

  // Group by host only when remotes are configured
  const hasRemoteHosts = hosts.length > 0;

  function renderRepoList(repoList: HostedRepository[]) {
    return repoList.map((repo) => {
        const isRepoExpanded = expandedRepos.has(repo.path);
        const isRepoSelected = selectedRepositoryPath === repo.path;
        const totalSessions = countSessions(repo);
        const activeCount = countActiveSessions(repo);
        const worktrees = lowerFilter
          ? (repo.worktrees ?? []).filter(worktreeMatchesFilter)
          : (repo.worktrees ?? []);

        return (
          <div key={repo.path} className="repo-node">
            {/* ── Repository header ── */}
            <div
              className={`repo-header ${isRepoSelected ? 'selected' : ''}`}
              onClick={() => {
                selectRepository(repo.path);
                if (!isRepoExpanded) toggleRepo(repo.path);
              }}
            >
              <button
                className={`expand-btn ${isRepoExpanded ? 'expanded' : ''}`}
                onClick={(e) => {
                  e.stopPropagation();
                  toggleRepo(repo.path);
                }}
              >
                <svg width="12" height="12" viewBox="0 0 12 12" fill="currentColor">
                  <path d="M4 2l4 4-4 4" />
                </svg>
              </button>
              <div className="repo-icon">
                <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
                  <path d="M2 2.5A2.5 2.5 0 014.5 0h8.75a.75.75 0 01.75.75v12.5a.75.75 0 01-.75.75h-2.5a.75.75 0 110-1.5h1.75v-2h-8a1 1 0 00-.714 1.7.75.75 0 01-1.072 1.05A2.495 2.495 0 012 11.5v-9zm10.5-1h-8a1 1 0 00-1 1v6.708A2.486 2.486 0 014.5 9h8V1.5z" />
                </svg>
              </div>
              <div className="repo-info">
                <span className="repo-name">{repo.name}</span>
              </div>
              <div className="repo-badges">
                {activeCount > 0 && (
                  <span className="running-badge">{activeCount}</span>
                )}
                <span className="session-count">{totalSessions}</span>
              </div>
              <div className="repo-actions">
                <button
                  className="repo-action-btn"
                  onClick={(e) => handleRemoveRepo(e, repo.path)}
                  title="Remove repository"
                >
                  <svg width="12" height="12" viewBox="0 0 16 16" fill="currentColor">
                    <path d="M3.72 3.72a.75.75 0 011.06 0L8 6.94l3.22-3.22a.749.749 0 011.275.326.749.749 0 01-.215.734L9.06 8l3.22 3.22a.749.749 0 01-.326 1.275.749.749 0 01-.734-.215L8 9.06l-3.22 3.22a.751.751 0 01-1.042-.018.751.751 0 01-.018-1.042L6.94 8 3.72 4.78a.75.75 0 010-1.06z" />
                  </svg>
                </button>
              </div>
            </div>

            {/* ── Worktree children ── */}
            {isRepoExpanded && worktrees.length > 0 && (
              <div className="repo-sessions">
                {worktrees.map((wt) => {
                  const wtKey = `${repo.path}::${wt.path}`;
                  const isWtExpanded = expandedWorktrees.has(wtKey);
                  const sessions = lowerFilter
                    ? (wt.sessions ?? []).filter(sessionMatchesFilter)
                    : (wt.sessions ?? []);

                  return (
                    <WorktreeNode
                      key={wt.path}
                      worktree={wt}
                      sessions={sessions}
                      isExpanded={isWtExpanded}
                      onToggle={() => toggleWorktree(wtKey)}
                      selectedSessionId={selectedSessionId}
                      sessionStates={sessionStates}
                      monitoredSessionIds={monitoredSessionIds}
                      onSessionClick={handleSessionClick}
                      onSessionDoubleClick={handleSessionDoubleClick}
                      onDeleteWorktree={handleDeleteWorktree}
                      onStartSession={handleStartSession}
                    />
                  );
                })}
              </div>
            )}

            {isRepoExpanded && worktrees.length === 0 && (
              <div className="repo-empty">
                <span>No sessions</span>
              </div>
            )}
          </div>
        );
      });
  }

  if (!hasRemoteHosts) {
    return <div className="repo-tree">{renderRepoList(filteredRepos)}</div>;
  }

  const [collapsedHosts, setCollapsedHosts] = useState<Set<string>>(() => new Set());

  const toggleHost = useCallback((hostId: string) => {
    setCollapsedHosts((prev) => {
      const next = new Set(prev);
      if (next.has(hostId)) next.delete(hostId);
      else next.add(hostId);
      return next;
    });
  }, []);

  // Group by host
  const reposByHost = new Map<string, HostedRepository[]>();
  reposByHost.set(LOCALHOST_HOST_ID, []);
  for (const h of hosts) reposByHost.set(h.id, []);
  for (const repo of filteredRepos) {
    const hostId = repo.host_id ?? LOCALHOST_HOST_ID;
    if (!reposByHost.has(hostId)) reposByHost.set(hostId, []);
    reposByHost.get(hostId)!.push(repo);
  }

  function hostLabel(hostId: string): string {
    if (hostId === LOCALHOST_HOST_ID) return 'Local';
    return hosts.find((h) => h.id === hostId)?.label ?? hostId;
  }

  function hostStatus(hostId: string): ConnectionStatus {
    if (hostId === LOCALHOST_HOST_ID) return 'connected';
    return runtimeState[hostId]?.status ?? 'disconnected';
  }

  const statusDotColor: Record<ConnectionStatus, string> = {
    connected: 'var(--accent-green, #3fb950)',
    connecting: 'var(--accent-yellow, #d29922)',
    error: 'var(--accent-red, #ff7b72)',
    disconnected: 'var(--text-tertiary)',
  };

  return (
    <div className="repo-tree">
      {[...reposByHost.entries()].map(([hostId, hostRepos]) => {
        const isCollapsed = collapsedHosts.has(hostId);
        return (
          <div key={hostId} className="host-group">
            <div className="host-group-header" onClick={() => toggleHost(hostId)} style={{ cursor: 'pointer' }}>
              <button
                className={`expand-btn ${isCollapsed ? '' : 'expanded'}`}
                onClick={(e) => { e.stopPropagation(); toggleHost(hostId); }}
                style={{ flexShrink: 0 }}
              >
                <svg width="12" height="12" viewBox="0 0 12 12" fill="currentColor">
                  <path d="M4 2l4 4-4 4" />
                </svg>
              </button>
              <span
                className="status-dot"
                style={{
                  backgroundColor: statusDotColor[hostStatus(hostId)],
                  width: 7,
                  height: 7,
                  flexShrink: 0,
                }}
              />
              <span className="host-group-label">{hostLabel(hostId)}</span>
              {hostId !== LOCALHOST_HOST_ID && (() => {
                const st = hostStatus(hostId);
                if (st === 'connected') {
                  return (
                    <button
                      className="btn btn-ghost btn-xs"
                      style={{ marginLeft: 'auto', padding: '1px 5px', fontSize: 10 }}
                      onClick={(e) => { e.stopPropagation(); disconnectHost(hostId); }}
                    >
                      Disconnect
                    </button>
                  );
                }
                return (
                  <button
                    className="btn btn-primary btn-xs"
                    style={{ marginLeft: 'auto', padding: '1px 5px', fontSize: 10 }}
                    onClick={(e) => { e.stopPropagation(); connectHost(hostId); }}
                    disabled={st === 'connecting'}
                  >
                    {st === 'connecting' ? '…' : 'Connect'}
                  </button>
                );
              })()}
            </div>
            {!isCollapsed && renderRepoList(hostRepos)}
          </div>
        );
      })}
    </div>
  );
};

/* ──────────────────────────────────────────────────────
   Worktree sub-node
   ────────────────────────────────────────────────────── */

interface WorktreeNodeProps {
  worktree: WorktreeBranch;
  sessions: CLISession[];
  isExpanded: boolean;
  onToggle: () => void;
  selectedSessionId: string | null;
  sessionStates: Record<string, import('@/types/generated').SessionMonitorState>;
  monitoredSessionIds: Set<string>;
  onSessionClick: (session: CLISession) => void;
  onSessionDoubleClick: (session: CLISession) => void;
  onDeleteWorktree: (e: React.MouseEvent, worktreePath: string) => void;
  onStartSession: (e: React.MouseEvent, projectPath: string) => void;
}

const WorktreeNode: React.FC<WorktreeNodeProps> = ({
  worktree,
  sessions,
  isExpanded,
  onToggle,
  selectedSessionId,
  sessionStates,
  monitoredSessionIds,
  onSessionClick,
  onSessionDoubleClick,
  onDeleteWorktree,
  onStartSession,
}) => {
  const sortedSessions = [...sessions].sort(
    (a, b) =>
      new Date(b.last_activity_at).getTime() -
      new Date(a.last_activity_at).getTime(),
  );

  return (
    <div className="repo-node">
      <div className="repo-header" onClick={onToggle}>
        <button
          className={`expand-btn ${isExpanded ? 'expanded' : ''}`}
          onClick={(e) => {
            e.stopPropagation();
            onToggle();
          }}
        >
          <svg width="12" height="12" viewBox="0 0 12 12" fill="currentColor">
            <path d="M4 2l4 4-4 4" />
          </svg>
        </button>
        <div className="repo-icon">
          {worktree.is_worktree ? (
            /* git-branch icon */
            <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
              <path d="M11.75 2.5a.75.75 0 100 1.5.75.75 0 000-1.5zm-2.25.75a2.25 2.25 0 113 2.122V6A2.5 2.5 0 0110 8.5H6a1 1 0 00-1 1v1.128a2.251 2.251 0 11-1.5 0V5.372a2.25 2.25 0 111.5 0v1.836A2.492 2.492 0 016 7h4a1 1 0 001-1v-.628A2.25 2.25 0 019.5 3.25zM4.25 12a.75.75 0 100-1.5.75.75 0 000 1.5zM3.5 3.25a.75.75 0 111.5 0 .75.75 0 01-1.5 0z" />
            </svg>
          ) : (
            /* folder icon */
            <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
              <path d="M1.75 1A1.75 1.75 0 000 2.75v10.5C0 14.216.784 15 1.75 15h12.5A1.75 1.75 0 0016 13.25v-8.5A1.75 1.75 0 0014.25 3H7.5a.25.25 0 01-.2-.1l-.9-1.2C6.07 1.26 5.55 1 5 1H1.75z" />
            </svg>
          )}
        </div>
        <div className="repo-info">
          <span className="repo-name">{worktree.name}</span>
          {worktree.is_worktree && (
            <span className="repo-branch">worktree</span>
          )}
        </div>
        <div className="repo-badges">
          <span className="session-count">{sessions.length}</span>
        </div>
        <div className="repo-actions">
          <button
            className="repo-action-btn"
            onClick={(e) => onStartSession(e, worktree.path)}
            title="Start new session"
          >
            <svg width="12" height="12" viewBox="0 0 16 16" fill="currentColor">
              <path d="M8 2a.75.75 0 01.75.75v4.5h4.5a.75.75 0 010 1.5h-4.5v4.5a.75.75 0 01-1.5 0v-4.5h-4.5a.75.75 0 010-1.5h4.5v-4.5A.75.75 0 018 2z" />
            </svg>
          </button>
          {worktree.is_worktree && (
            <button
              className="repo-action-btn repo-action-danger"
              onClick={(e) => onDeleteWorktree(e, worktree.path)}
              title="Delete worktree"
            >
              <svg width="12" height="12" viewBox="0 0 16 16" fill="currentColor">
                <path d="M11 1.75V3h2.25a.75.75 0 010 1.5H2.75a.75.75 0 010-1.5H5V1.75C5 .784 5.784 0 6.75 0h2.5C10.216 0 11 .784 11 1.75zm-5.5 0V3h5V1.75a.25.25 0 00-.25-.25h-4.5a.25.25 0 00-.25.25zM4.997 6.178a.75.75 0 10-1.493.144L4.916 14H11.08l1.413-7.678a.75.75 0 00-1.493-.144L9.706 13H6.29L4.997 6.178z" />
              </svg>
            </button>
          )}
        </div>
      </div>

      {isExpanded && sortedSessions.length > 0 && (
        <div className="repo-sessions">
          {sortedSessions.map((session) => (
            <div key={session.id} data-session-id={session.id}>
              <SessionRow
                session={session}
                isSelected={selectedSessionId === session.id}
                isMonitored={monitoredSessionIds.has(session.id)}
                monitorState={sessionStates[session.id]}
                onClick={() => onSessionClick(session)}
                onDoubleClick={() => onSessionDoubleClick(session)}
              />
            </div>
          ))}
        </div>
      )}

      {isExpanded && sortedSessions.length === 0 && (
        <div className="repo-empty">
          <span>No sessions</span>
        </div>
      )}
    </div>
  );
};
