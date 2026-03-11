import React, { useState, useCallback, useEffect } from 'react';
import type { DetailView } from '@/components/layout/AppLayout';
import type { CLISession } from '@/types/generated';
import { SessionId } from "@/types/session";
import { useSessionsStore } from '@/store/sessions';
import { MonitoringCardView } from './MonitoringCardView';
import { SessionHistoryView } from './SessionHistoryView';

interface SessionViewProps {
  sessionId: SessionId;
  session: CLISession;
  onChangeView?: (view: DetailView) => void;
}

/** Map MonitoringCard action strings to detail view tabs. */
const ACTION_TO_VIEW: Record<string, DetailView> = {
  edits: 'changes',
  plan: 'plan',
  diff: 'changes',
  preview: 'terminal',
  diagram: 'diagram',
};

export const SessionView: React.FC<SessionViewProps> = ({
  sessionId,
  session,
  onChangeView,
}) => {
  const monitoredSessionIds = useSessionsStore((s) => s.monitoredSessionIds);
  const sessionState = useSessionsStore((s) => s.sessionStates[sessionId]);
  const startMonitoring = useSessionsStore((s) => s.startMonitoring);
  const stopMonitoring = useSessionsStore((s) => s.stopMonitoring);
  const refreshSessionState = useSessionsStore((s) => s.refreshSessionState);

  const isMonitored = monitoredSessionIds.has(sessionId);
  const [expanded, setExpanded] = useState(isMonitored);

  // Auto-expand when monitoring starts, collapse when it stops
  useEffect(() => {
    setExpanded(isMonitored);
  }, [isMonitored]);

  const handleStartMonitoring = () => {
    startMonitoring(sessionId, session.project_path, session.session_file_path);
  };

  const handleCardAction = useCallback(
    (action: string, _sessionId: SessionId) => {
      if (action === 'refresh') {
        refreshSessionState?.(_sessionId);
        return;
      }
      const view = ACTION_TO_VIEW[action];
      if (view && onChangeView) {
        onChangeView(view);
      }
    },
    [onChangeView, refreshSessionState],
  );

  // Build collapsed summary line
  const statusKind = sessionState?.status?.kind ?? 'idle';
  const inputTokens = sessionState?.input_tokens ?? 0;
  const outputTokens = sessionState?.output_tokens ?? 0;
  const tokenSummary = `${Math.round(inputTokens / 1000)}k/${Math.round(outputTokens / 1000)}k`;
  const msgCount = sessionState?.message_count ?? 0;

  return (
    <div className="session-view">
      {/* Collapsible monitoring panel */}
      <div className="session-monitor-panel">
        {isMonitored ? (
          <>
            <div
              className="session-monitor-collapsed-bar"
              onClick={() => setExpanded(!expanded)}
            >
              <span className="session-expand-icon">
                {expanded ? '\u25BC' : '\u25B6'}
              </span>
              <span
                className="status-dot"
                style={{
                  backgroundColor:
                    statusKind === 'thinking'
                      ? 'var(--accent-purple)'
                      : statusKind === 'executing_tool'
                        ? 'var(--accent-blue)'
                        : statusKind === 'waiting_for_user'
                          ? 'var(--accent-orange)'
                          : statusKind === 'awaiting_approval'
                            ? 'var(--accent-yellow)'
                            : 'var(--text-tertiary)',
                  animation:
                    statusKind === 'thinking' || statusKind === 'executing_tool'
                      ? 'pulse 1.5s ease-in-out infinite'
                      : 'none',
                }}
              />
              <span className="session-monitor-status-label">
                {statusKind === 'thinking'
                  ? 'Thinking'
                  : statusKind === 'executing_tool'
                    ? `Running: ${sessionState?.status?.kind === 'executing_tool' ? (sessionState.status as any).name : ''}`
                    : statusKind === 'waiting_for_user'
                      ? 'Waiting'
                      : statusKind === 'awaiting_approval'
                        ? 'Approval'
                        : 'Idle'}
              </span>
              <span className="session-monitor-summary mono">
                {tokenSummary}
              </span>
              <span className="session-monitor-summary mono">
                {msgCount} msgs
              </span>
              <span style={{ flex: 1 }} />
              <button
                className="btn btn-ghost"
                style={{
                  padding: '1px 6px',
                  fontSize: 'var(--font-size-xs)',
                  color: 'var(--text-tertiary)',
                }}
                onClick={(e) => {
                  e.stopPropagation();
                  stopMonitoring(sessionId);
                }}
              >
                Stop
              </button>
            </div>
            {expanded && (
              <div className="session-monitor-expanded">
                <MonitoringCardView
                  sessionId={sessionId}
                  session={session}
                  onAction={handleCardAction}
                />
              </div>
            )}
          </>
        ) : (
          <div
            className="session-monitor-collapsed-bar"
            onClick={() => setExpanded(!expanded)}
          >
            <span className="session-expand-icon">
              {expanded ? '\u25BC' : '\u25B6'}
            </span>
            <span
              className="status-dot"
              style={{ backgroundColor: 'var(--text-tertiary)' }}
            />
            <button
              className="btn btn-primary"
              style={{ padding: '2px 10px', fontSize: 'var(--font-size-xs)' }}
              onClick={(e) => {
                e.stopPropagation();
                handleStartMonitoring();
              }}
            >
              Start Monitoring
            </button>
            <span className="session-monitor-status-label" style={{ color: 'var(--text-tertiary)' }}>
              Not monitored
            </span>
          </div>
        )}
      </div>

      {/* History always visible below */}
      <div className="session-history-section">
        <SessionHistoryView sessionId={sessionId} isMonitored={isMonitored} />
      </div>
    </div>
  );
};
