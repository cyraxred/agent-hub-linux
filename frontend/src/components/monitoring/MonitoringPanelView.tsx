import { SessionId } from '@/types/session';
import React, { useState, useMemo, useCallback } from 'react';
import type { CLISession } from '@/types/generated';
import { useSessionsStore } from '@/store/sessions';
import { MonitoringCardView } from './MonitoringCardView';

type LayoutMode = 'single' | 'list' | '2-col' | '3-col';

type SidePanelState =
  | { visible: false }
  | { visible: true; action: string; sessionId: SessionId };

/**
 * Resolve grid column template based on layout mode.
 */
function gridColumns(layout: LayoutMode): string {
  switch (layout) {
    case 'single':
      return '1fr';
    case 'list':
      return '1fr';
    case '2-col':
      return '1fr 1fr';
    case '3-col':
      return '1fr 1fr 1fr';
  }
}

/**
 * Lookup a CLISession by id from the repository tree.
 */
function findSession(
  repositories: ReturnType<typeof useSessionsStore.getState>['repositories'],
  sessionId: SessionId,
): CLISession | undefined {
  for (const repo of repositories) {
    for (const wt of repo.worktrees ?? []) {
      const found = wt.sessions?.find((s) => s.id === sessionId);
      if (found) return found;
    }
  }
  return undefined;
}

export const MonitoringPanelView: React.FC = () => {
  const monitoredSessionIds = useSessionsStore((s) => s.monitoredSessionIds);
  const repositories = useSessionsStore((s) => s.repositories);
  const stopMonitoring = useSessionsStore((s) => s.stopMonitoring);

  const [layout, setLayout] = useState<LayoutMode>('2-col');
  const [sidePanel, setSidePanel] = useState<SidePanelState>({ visible: false });

  const monitoredIds = useMemo(() => Array.from(monitoredSessionIds), [monitoredSessionIds]);

  /**
   * Build a map of sessionId -> CLISession for all monitored sessions.
   */
  const sessionsMap = useMemo(() => {
    const map: Record<string, CLISession> = {};
    for (const id of monitoredIds) {
      const session = findSession(repositories, id);
      if (session) {
        map[id] = session;
      }
    }
    return map;
  }, [monitoredIds, repositories]);

  const handleCardAction = useCallback(
    (action: string, sessionId: SessionId) => {
      if (action === 'maximize') {
        // Switch to single layout focused on this card
        setLayout('single');
        return;
      }
      // For edits/plan/diff/preview/diagram/refresh - open side panel
      if (['edits', 'plan', 'diff', 'preview', 'diagram'].includes(action)) {
        setSidePanel({ visible: true, action, sessionId });
        return;
      }
      if (action === 'refresh') {
        // Trigger a state refresh for this session (via stop + re-start monitoring)
        // For now just close the side panel if open
        setSidePanel((prev) => (prev.visible && prev.sessionId === sessionId ? { visible: false } : prev));
      }
    },
    [],
  );

  const closeSidePanel = useCallback(() => {
    setSidePanel((prev) => ({ ...prev, visible: false }));
  }, []);

  if (monitoredIds.length === 0) {
    return (
      <div className="monitoring-panel">
        <div className="detail-empty">
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
            <path d="M9 17.25v1.007a3 3 0 01-.879 2.122L7.5 21h9l-.621-.621A3 3 0 0115 18.257V17.25m6-12V15a2.25 2.25 0 01-2.25 2.25H5.25A2.25 2.25 0 013 15V5.25A2.25 2.25 0 015.25 3h13.5A2.25 2.25 0 0121 5.25z" />
          </svg>
          <h2>No Monitored Sessions</h2>
          <p>
            Select a session from the sidebar and start monitoring to see live updates here.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="monitoring-panel" style={{ display: 'flex', flexDirection: 'row', height: '100%' }}>
      {/* Main grid area */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        {/* Layout mode selector */}
        <div className="monitor-mode-tabs">
          {(
            [
              { key: 'single' as const, label: '1' },
              { key: 'list' as const, label: 'List' },
              { key: '2-col' as const, label: '2-Col' },
              { key: '3-col' as const, label: '3-Col' },
            ]
          ).map(({ key, label }) => (
            <button
              key={key}
              className={`monitor-mode-tab ${layout === key ? 'active' : ''}`}
              onClick={() => setLayout(key)}
            >
              {label}
            </button>
          ))}
          <span style={{ flex: 1 }} />
          <span
            style={{
              fontSize: 'var(--font-size-xs)',
              color: 'var(--text-tertiary)',
              alignSelf: 'center',
            }}
          >
            {monitoredIds.length} session{monitoredIds.length !== 1 ? 's' : ''}
          </span>
        </div>

        {/* Card grid */}
        <div
          className="monitor-mode-content"
          style={{
            display: 'grid',
            gridTemplateColumns: gridColumns(layout),
            gap: 'var(--space-lg)',
            alignContent: 'start',
          }}
        >
          {monitoredIds.map((id) => {
            const session = sessionsMap[id];
            if (!session) return null;
            return (
              <MonitoringCardView
                key={id}
                sessionId={id}
                session={session}
                onAction={handleCardAction}
              />
            );
          })}
        </div>
      </div>

      {/* Optional side panel for diff/plan/preview */}
      {sidePanel.visible && (
        <div
          style={{
            width: 480,
            borderLeft: '1px solid var(--border-default)',
            display: 'flex',
            flexDirection: 'column',
            background: 'var(--bg-secondary)',
            flexShrink: 0,
            overflow: 'hidden',
          }}
        >
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              padding: 'var(--space-md) var(--space-lg)',
              borderBottom: '1px solid var(--border-muted)',
              flexShrink: 0,
            }}
          >
            <span
              style={{
                fontSize: 'var(--font-size-sm)',
                fontWeight: 600,
                textTransform: 'capitalize',
                color: 'var(--text-secondary)',
              }}
            >
              {sidePanel.action}
            </span>
            <button className="btn btn-ghost" onClick={closeSidePanel} style={{ padding: '2px 8px' }}>
              Close
            </button>
          </div>
          <div
            style={{
              flex: 1,
              overflow: 'auto',
              padding: 'var(--space-lg)',
              color: 'var(--text-tertiary)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            <p>
              {sidePanel.action} view for session {sidePanel.sessionId.slice(0, 8)}
            </p>
          </div>
        </div>
      )}
    </div>
  );
};
