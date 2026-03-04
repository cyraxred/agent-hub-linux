import React, { useState } from 'react';
import { useSessionsStore } from '@/store/sessions';
import { useSettingsStore } from '@/store/settings';
import { RepositoryTreeView } from '@/components/sessions/RepositoryTreeView';
import { ProviderSegmentedControl } from '@/components/sessions/ProviderSegmentedControl';
import type { CLISession } from '@/types/generated';

const TIMEOUT_OPTIONS = [0, 3, 5, 10, 15, 30] as const;

interface SidebarProps {
  collapsed: boolean;
  sessionData: {
    repositories: import('@/types/generated').SelectedRepository[];
    allSessions: CLISession[];
    monitoredSessionIds: Set<string>;
    sessionStates: Record<string, import('@/types/generated').SessionMonitorState>;
    selectedRepositoryPath: string | null;
    selectedSessionId: string | null;
    activeProvider: string;
    loading: boolean;
    selectRepository: (path: string | null) => void;
  };
}

export const Sidebar: React.FC<SidebarProps> = ({ collapsed, sessionData }) => {
  const {
    repositories,
    allSessions,
    monitoredSessionIds,
    sessionStates,
    selectedRepositoryPath,
    selectedSessionId,
    activeProvider,
    loading,
    selectRepository,
  } = sessionData;

  const selectSession = useSessionsStore((s) => s.selectSession);
  const addRepository = useSessionsStore((s) => s.addRepository);
  const { settings, updateSettings, saveSettings } = useSettingsStore();
  const approvalTimeout = (settings.approval_timeout_seconds as number) ?? 10;

  const [showAddRepo, setShowAddRepo] = useState(false);
  const [newRepoPath, setNewRepoPath] = useState('');
  const [addingRepo, setAddingRepo] = useState(false);
  const [addRepoError, setAddRepoError] = useState<string | null>(null);
  const [filterText, setFilterText] = useState('');

  const handleAddRepo = async () => {
    const trimmed = newRepoPath.trim();
    if (!trimmed) return;
    setAddingRepo(true);
    setAddRepoError(null);
    try {
      await addRepository(trimmed);
      setShowAddRepo(false);
      setNewRepoPath('');
    } catch (err) {
      setAddRepoError((err as Error).message);
    } finally {
      setAddingRepo(false);
    }
  };

  const handleCancelAddRepo = () => {
    setShowAddRepo(false);
    setNewRepoPath('');
    setAddRepoError(null);
  };

  if (collapsed) {
    return (
      <aside className="sidebar collapsed">
        <div className="sidebar-collapsed-icons">
          {repositories.map((repo) => (
            <button
              key={repo.path}
              className={`sidebar-icon ${selectedRepositoryPath === repo.path ? 'active' : ''}`}
              onClick={() => selectRepository(repo.path)}
              title={repo.name}
            >
              {repo.name.charAt(0).toUpperCase()}
            </button>
          ))}
        </div>
      </aside>
    );
  }

  // Count running sessions (those with an active monitor state that is not idle)
  const runningSessions = allSessions.filter((s) => {
    if (!monitoredSessionIds.has(s.id)) return s.is_active;
    const state = sessionStates[s.id];
    return state?.status && state.status.kind !== 'idle';
  });

  return (
    <aside className="sidebar">
      <div className="sidebar-section">
        <div className="sidebar-section-header">
          <h3>Repositories</h3>
          <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-sm)' }}>
            <span className="badge">{repositories.length}</span>
            <button
              className="btn btn-ghost btn-xs"
              onClick={() => setShowAddRepo(!showAddRepo)}
              title="Add repository"
              style={{ padding: '2px 6px', lineHeight: 1 }}
            >
              <svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor">
                <path d="M7.75 2a.75.75 0 01.75.75V7h4.25a.75.75 0 010 1.5H8.5v4.25a.75.75 0 01-1.5 0V8.5H2.75a.75.75 0 010-1.5H7V2.75A.75.75 0 017.75 2z" />
              </svg>
            </button>
          </div>
        </div>

        {showAddRepo && (
          <div className="sidebar-add-repo">
            <input
              type="text"
              className="setting-input"
              placeholder="/path/to/repository"
              value={newRepoPath}
              onChange={(e) => setNewRepoPath(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') handleAddRepo();
                if (e.key === 'Escape') handleCancelAddRepo();
              }}
              autoFocus
              disabled={addingRepo}
            />
            <div style={{ display: 'flex', gap: 'var(--space-sm)', marginTop: 'var(--space-sm)' }}>
              <button
                className="btn btn-primary btn-xs"
                onClick={handleAddRepo}
                disabled={!newRepoPath.trim() || addingRepo}
              >
                {addingRepo ? 'Adding...' : 'Add'}
              </button>
              <button className="btn btn-ghost btn-xs" onClick={handleCancelAddRepo}>
                Cancel
              </button>
            </div>
            {addRepoError && (
              <span className="text-error" style={{ fontSize: 'var(--font-size-xs)', marginTop: 'var(--space-xs)' }}>
                {addRepoError}
              </span>
            )}
          </div>
        )}

        {/* ProviderSegmentedControl reads from the store directly */}
        <ProviderSegmentedControl />
      </div>

      {repositories.length > 0 && (
        <div className="sidebar-search">
          <svg className="sidebar-search-icon" width="12" height="12" viewBox="0 0 16 16" fill="currentColor">
            <path d="M11.742 10.344a6.5 6.5 0 1 0-1.397 1.398h-.001c.03.04.062.078.098.115l3.85 3.85a1 1 0 0 0 1.415-1.414l-3.85-3.85a1.007 1.007 0 0 0-.115-.1zM12 6.5a5.5 5.5 0 1 1-11 0 5.5 5.5 0 0 1 11 0z" />
          </svg>
          <input
            type="text"
            className="sidebar-search-input"
            placeholder="Filter sessions..."
            value={filterText}
            onChange={(e) => setFilterText(e.target.value)}
          />
          {filterText && (
            <button
              className="sidebar-search-clear"
              onClick={() => setFilterText('')}
              title="Clear filter"
            >
              <svg width="10" height="10" viewBox="0 0 16 16" fill="currentColor">
                <path d="M3.72 3.72a.75.75 0 011.06 0L8 6.94l3.22-3.22a.749.749 0 011.275.326.749.749 0 01-.215.734L9.06 8l3.22 3.22a.749.749 0 01-.326 1.275.749.749 0 01-.734-.215L8 9.06l-3.22 3.22a.751.751 0 01-1.042-.018.751.751 0 01-.018-1.042L6.94 8 3.72 4.78a.75.75 0 010-1.06z" />
              </svg>
            </button>
          )}
        </div>
      )}

      <div className="sidebar-section sidebar-tree">
        {loading && repositories.length === 0 ? (
          <div className="sidebar-empty">
            <div className="spinner" />
            <span>Loading repositories...</span>
          </div>
        ) : repositories.length === 0 ? (
          <div className="sidebar-empty">
            <svg
              width="32"
              height="32"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.5"
            >
              <path d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
            </svg>
            <span>No repositories added</span>
            <span className="sidebar-empty-hint">
              Click + above to add a repository
            </span>
          </div>
        ) : (
          <RepositoryTreeView filter={filterText} />
        )}
      </div>

      {/* Monitored Sessions Panel */}
      {monitoredSessionIds.size > 0 && (
        <div className="sidebar-section">
          <div className="sidebar-section-header">
            <h3>Monitored</h3>
            <span className="badge">{monitoredSessionIds.size}</span>
          </div>
          <div className="sidebar-monitored-list">
            {Array.from(monitoredSessionIds).map((sessionId) => {
              const state = sessionStates[sessionId];
              const statusKind = state?.status?.kind ?? 'idle';
              return (
                <button
                  key={sessionId}
                  className={`sidebar-monitored-item ${
                    selectedSessionId === sessionId ? 'active' : ''
                  }`}
                  onClick={() => selectSession(sessionId)}
                  title={sessionId}
                >
                  <span className={`status-dot status-${statusKind}`} />
                  <span className="monitored-session-id">
                    {sessionId.slice(0, 12)}
                  </span>
                  <span className="monitored-session-status">{statusKind}</span>
                </button>
              );
            })}
          </div>
        </div>
      )}

      <div className="sidebar-footer">
        <div className="sidebar-stats">
          <div className="sidebar-stat">
            <span className="stat-label">Running</span>
            <span className="stat-value running">{runningSessions.length}</span>
          </div>
          <div className="sidebar-stat">
            <span className="stat-label">Total</span>
            <span className="stat-value">{allSessions.length}</span>
          </div>
          <div className="sidebar-stat">
            <span className="stat-label">Approve</span>
            <select
              className="sidebar-timeout-select"
              value={approvalTimeout}
              onChange={(e) => {
                updateSettings({ approval_timeout_seconds: parseInt(e.target.value, 10) });
                saveSettings();
              }}
              title="Auto-approve timeout (0 = never)"
            >
              {TIMEOUT_OPTIONS.map((v) => (
                <option key={v} value={v}>
                  {v === 0 ? 'Off' : `${v}s`}
                </option>
              ))}
            </select>
          </div>
        </div>
      </div>
    </aside>
  );
};
