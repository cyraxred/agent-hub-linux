import React from 'react';
import type { DetailView } from './AppLayout';
import type { CLISession, SelectedRepository, SessionMonitorState } from '@/types/generated';
import { EmbeddedTerminal } from '@/components/terminal/EmbeddedTerminal';
import { PendingChangesView } from '@/components/diff/PendingChangesView';
import { PlanView } from '@/components/plan/PlanView';
import { MermaidDiagramView } from '@/components/diagram/MermaidDiagramView';
import { SessionView } from '@/components/monitoring/SessionView';
import { SettingsView } from '@/components/settings/SettingsView';
import { MultiSessionLaunchView } from '@/components/launcher/MultiSessionLaunchView';

interface DetailPanelProps {
  activeView: DetailView;
  sessionData: {
    selectedSession: CLISession | null;
    selectedSessionId: string | null;
    selectedRepositoryPath: string | null;
    repositories: SelectedRepository[];
    monitoredSessionIds: Set<string>;
    sessionStates: Record<string, SessionMonitorState>;
  };
  onChangeView?: (view: DetailView) => void;
}

export const DetailPanel: React.FC<DetailPanelProps> = ({
  activeView,
  sessionData,
  onChangeView,
}) => {
  const {
    selectedSession,
    monitoredSessionIds,
    sessionStates,
  } = sessionData;

  // Settings and launcher views do not require a selected session
  if (activeView === 'settings') {
    return (
      <main className="detail-panel">
        <SettingsView />
      </main>
    );
  }

  if (activeView === 'launcher') {
    return (
      <main className="detail-panel">
        <MultiSessionLaunchView
          onLaunched={() => onChangeView?.('terminal')}
        />
      </main>
    );
  }

  // No session selected -- show empty state
  if (!selectedSession) {
    return (
      <main className="detail-panel">
        <div className="detail-empty">
          <svg
            width="48"
            height="48"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1"
          >
            <circle cx="12" cy="12" r="10" />
            <path d="M12 8v4M12 16h.01" />
          </svg>
          <h2>No Session Selected</h2>
          <p>
            Select a session from the sidebar to view its details, or use the
            Launch tab to create a new session.
          </p>
          <div className="detail-empty-shortcuts">
            <kbd>Ctrl</kbd>+<kbd>K</kbd> to search
          </div>
        </div>
      </main>
    );
  }

  const isMonitored = monitoredSessionIds.has(selectedSession.id);
  const sessionState = sessionStates[selectedSession.id];
  const statusKind = sessionState?.status?.kind ?? 'idle';

  const renderView = () => {
    switch (activeView) {
      case 'session':
        return (
          <SessionView
            sessionId={selectedSession.id}
            session={selectedSession}
            onChangeView={onChangeView}
          />
        );

      case 'terminal':
        return (
          <EmbeddedTerminal
            sessionId={selectedSession.id}
            projectPath={selectedSession.project_path}
          />
        );

      case 'changes':
        return (
          <PendingChangesView
            repoPath={selectedSession.project_path}
            sessionId={selectedSession.id}
            onTerminalLaunched={() => onChangeView?.('terminal')}
          />
        );

      case 'plan':
        return <PlanView sessionId={selectedSession.id} />;

      case 'diagram':
        return <MermaidDiagramView sessionId={selectedSession.id} />;

      default:
        return null;
    }
  };

  return (
    <main className="detail-panel">
      <div className="detail-header">
        <div className="detail-header-info">
          <h2 className="detail-title">
            {selectedSession.slug ?? selectedSession.id.slice(0, 12)}
          </h2>
          <div className="detail-meta">
            <span className={`status-badge status-${statusKind}`}>
              {statusKind}
            </span>
            <span className="meta-separator" />
            {selectedSession.branch_name && (
              <>
                <span className="branch-name">
                  {selectedSession.branch_name}
                </span>
                <span className="meta-separator" />
              </>
            )}
            {selectedSession.is_worktree && (
              <span className="provider-badge">worktree</span>
            )}
            {isMonitored && (
              <span className="provider-badge">monitored</span>
            )}
          </div>
        </div>
      </div>
      <div className="detail-content">{renderView()}</div>
    </main>
  );
};
