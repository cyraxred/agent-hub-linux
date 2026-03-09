import { useEffect, useMemo } from 'react';
import { useSessionsStore } from '@/store/sessions';
import { useWebSocket } from './useWebSocket';
import type { CLISession, SelectedRepository } from '@/types/generated';

const AUTO_REFRESH_INTERVAL = 10_000;

export function useSessions() {
  const {
    repositories,
    sessionStates,
    monitoredSessionIds,
    selectedSessionId,
    selectedRepositoryPath,
    activeProvider,
    loading,
    error,
    fetchRepositories,
    selectRepository,
    selectSession,
    setActiveProvider,
    refreshSessions,
    startMonitoring,
    stopMonitoring,
  } = useSessionsStore();

  const { connected, subscribe, unsubscribe } = useWebSocket();

  const loadSessionNames = useSessionsStore((s) => s.loadSessionNames);

  // Fetch repositories and persisted session names on mount
  useEffect(() => {
    fetchRepositories();
    loadSessionNames();
  }, [fetchRepositories, loadSessionNames]);

  // Auto-refresh repositories every 10 seconds
  useEffect(() => {
    const interval = setInterval(() => {
      refreshSessions();
    }, AUTO_REFRESH_INTERVAL);
    return () => clearInterval(interval);
  }, [refreshSessions]);

  const monitoredSessionInfo = useSessionsStore((s) => s.monitoredSessionInfo);

  // Subscribe to selected session via WS when it is being monitored.
  // Uses monitoredSessionInfo (stored at startMonitoring time) so this
  // doesn't depend on repositories being populated — no race condition.
  useEffect(() => {
    if (!selectedSessionId || !connected) return;
    if (!monitoredSessionIds.has(selectedSessionId)) return;

    const info = monitoredSessionInfo[selectedSessionId];
    if (!info) return;

    subscribe({
      sessionId: selectedSessionId,
      projectPath: info.projectPath,
      sessionFilePath: info.sessionFilePath,
    });

    return () => {
      unsubscribe(selectedSessionId);
    };
  }, [selectedSessionId, connected, monitoredSessionIds, monitoredSessionInfo, subscribe, unsubscribe]);

  // Compute: flatten all sessions from repos -> worktrees -> sessions
  const allSessions = useMemo(() => {
    const sessions: CLISession[] = [];
    for (const repo of repositories) {
      for (const wt of repo.worktrees ?? []) {
        for (const s of wt.sessions ?? []) {
          sessions.push(s);
        }
      }
    }
    return sessions;
  }, [repositories]);

  // Compute: selected session (find CLISession by selectedSessionId)
  const selectedSession = useMemo<CLISession | null>(() => {
    if (!selectedSessionId) return null;
    return allSessions.find((s) => s.id === selectedSessionId) ?? null;
  }, [allSessions, selectedSessionId]);

  // Compute: selected repository (find from repos by selectedRepositoryPath)
  const selectedRepository = useMemo<SelectedRepository | null>(() => {
    if (!selectedRepositoryPath) return null;
    return repositories.find((r) => r.path === selectedRepositoryPath) ?? null;
  }, [repositories, selectedRepositoryPath]);

  return {
    // Store state
    repositories,
    sessionStates,
    monitoredSessionIds,
    selectedSessionId,
    selectedRepositoryPath,
    activeProvider,
    loading,
    error,
    connected,

    // Computed values
    allSessions,
    selectedSession,
    selectedRepository,

    // Actions
    selectRepository,
    selectSession,
    setActiveProvider,
    refreshSessions,
    startMonitoring,
    stopMonitoring,
    fetchRepositories,
  };
}
