import React, { useState, useCallback } from 'react';
import type { CLISession, SessionMonitorState, ActivityEntry } from '@/types/generated';
import { useSessionsStore } from '@/store/sessions';
import { ContextWindowBar } from './ContextWindowBar';
import { EmbeddedTerminal } from '../terminal/EmbeddedTerminal';

type CardMode = 'monitor' | 'terminal';

interface MonitoringCardViewProps {
  sessionId: string;
  session: CLISession;
  onAction?: (action: string, sessionId: string) => void;
}

/**
 * Map status.kind to a CSS-friendly color for the animated dot.
 */
function getStatusDotColor(state?: SessionMonitorState): string {
  if (!state?.status) return 'var(--text-tertiary)';
  switch (state.status.kind) {
    case 'thinking':
      return 'var(--accent-purple)';
    case 'executing_tool':
      return 'var(--accent-blue)';
    case 'waiting_for_user':
      return 'var(--accent-orange)';
    case 'awaiting_approval':
    case 'awaiting_question':
      return 'var(--accent-yellow)';
    case 'idle':
    default:
      return 'var(--text-tertiary)';
  }
}

/**
 * Whether the dot should pulse (non-idle active states).
 */
function shouldPulse(state?: SessionMonitorState): boolean {
  if (!state?.status) return false;
  return state.status.kind === 'thinking' || state.status.kind === 'executing_tool';
}

/**
 * Human-readable status label from the discriminated union.
 */
function getStatusLabel(state?: SessionMonitorState): string {
  if (!state?.status) return 'Unknown';
  switch (state.status.kind) {
    case 'thinking':
      return 'Thinking';
    case 'executing_tool':
      return `Running: ${state.status.name}`;
    case 'waiting_for_user':
      return 'Waiting for User';
    case 'awaiting_approval':
      return `Approve: ${state.status.tool}`;
    case 'awaiting_question':
      return 'Awaiting Question';
    case 'idle':
    default:
      return 'Idle';
  }
}

/**
 * Truncate a path from the left, keeping the rightmost portion visible.
 */
function truncatePathLeft(path: string, maxLen: number): string {
  if (path.length <= maxLen) return path;
  return '\u2026' + path.slice(path.length - maxLen + 1);
}

/**
 * Format an ActivityEntry for display.
 */
function formatActivity(activity: ActivityEntry): string {
  if (activity.description) return activity.description;
  switch (activity.type.kind) {
    case 'tool_use':
      return `Tool: ${activity.type.name}`;
    case 'tool_result':
      return `${activity.type.name}: ${activity.type.success ? 'success' : 'failed'}`;
    case 'user_message':
      return 'User message';
    case 'assistant_message':
      return 'Assistant message';
    case 'thinking':
      return 'Thinking...';
  }
}

/**
 * CSS class suffix for activity type badge styling.
 */
function activityTypeClass(activity: ActivityEntry): string {
  switch (activity.type.kind) {
    case 'tool_use':
    case 'tool_result':
      return 'tool_use';
    case 'user_message':
    case 'assistant_message':
      return 'message';
    case 'thinking':
      return 'thinking';
  }
}

function activityTypeBadge(activity: ActivityEntry): string {
  switch (activity.type.kind) {
    case 'tool_use':
      return activity.type.name;
    case 'tool_result':
      return activity.type.name;
    case 'user_message':
      return 'user';
    case 'assistant_message':
      return 'assistant';
    case 'thinking':
      return 'thinking';
  }
}

export const MonitoringCardView: React.FC<MonitoringCardViewProps> = ({
  sessionId,
  session,
  onAction,
}) => {
  const state = useSessionsStore((s) => s.sessionStates[sessionId]);
  const stopMonitoring = useSessionsStore((s) => s.stopMonitoring);
  const [mode, setMode] = useState<CardMode>('monitor');

  const dotColor = getStatusDotColor(state);
  const pulse = shouldPulse(state);
  const label = session.slug || sessionId.slice(0, 8);

  const handleAction = useCallback(
    (action: string) => {
      onAction?.(action, sessionId);
    },
    [onAction, sessionId],
  );

  const recentActivities: ActivityEntry[] = (state?.recent_activities ?? []).slice(-3).reverse();
  const totalToolCalls = state?.tool_calls
    ? Object.values(state.tool_calls).reduce((sum, n) => sum + n, 0)
    : 0;

  return (
    <div className="monitor-card">
      {/* ── Header Row ── */}
      <div className="monitor-card-header">
        <span
          className="status-dot"
          style={{
            backgroundColor: dotColor,
            animation: pulse ? 'pulse 1.5s ease-in-out infinite' : 'none',
          }}
        />
        <span style={{ flex: 1 }}>{label}</span>
        {state?.model && <span className="provider-badge">{state.model}</span>}
        <button
          className="btn-ghost btn"
          style={{ padding: '2px 6px', fontSize: 'var(--font-size-xs)', color: 'var(--text-tertiary)' }}
          onClick={() => stopMonitoring(sessionId)}
          title="Stop monitoring this session"
        >
          Stop
        </button>
        <button
          className="btn-ghost btn"
          style={{ padding: '2px 6px', fontSize: 'var(--font-size-xs)' }}
          onClick={() => setMode(mode === 'monitor' ? 'terminal' : 'monitor')}
          title={mode === 'monitor' ? 'Switch to terminal' : 'Switch to monitor'}
        >
          {mode === 'monitor' ? 'Terminal' : 'Monitor'}
        </button>
      </div>

      {/* ── Path Row ── */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 'var(--space-sm)',
          padding: '4px var(--space-lg)',
          borderBottom: '1px solid var(--border-muted)',
          fontSize: 'var(--font-size-xs)',
          flexWrap: 'wrap',
        }}
      >
        <span
          className="mono"
          style={{ color: 'var(--text-tertiary)', direction: 'rtl', textAlign: 'left', maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
          title={session.project_path}
        >
          {truncatePathLeft(session.project_path, 40)}
        </span>
        {session.branch_name && (
          <span className="branch-name" style={{ color: 'var(--accent-blue)' }}>
            {session.branch_name}
          </span>
        )}
        <span style={{ flex: 1 }} />
        {/* Action buttons */}
        {(
          [
            { key: 'edits', label: 'Edits' },
            { key: 'plan', label: (state?.plans?.length ?? 0) > 1 ? `Plan (${state!.plans!.length})` : 'Plan' },
            { key: 'diff', label: 'Diff' },
            { key: 'preview', label: 'Preview' },
            ...((state?.mermaid_diagrams?.length ?? 0) > 0 || state?.has_mermaid_content
              ? [{ key: 'diagram', label: (state?.mermaid_diagrams?.length ?? 0) > 1 ? `Diagram (${state!.mermaid_diagrams!.length})` : 'Diagram' }]
              : []),
            { key: 'refresh', label: 'Refresh' },
          ] as { key: string; label: string }[]
        ).map(({ key, label: btnLabel }) => (
          <button
            key={key}
            className="btn btn-ghost"
            style={{ padding: '1px 6px', fontSize: 'var(--font-size-xs)' }}
            onClick={() => handleAction(key)}
          >
            {btnLabel}
          </button>
        ))}
      </div>

      {/* ── Context Window Bar ── */}
      {state && (
        <div style={{ padding: 'var(--space-sm) var(--space-lg)' }}>
          <ContextWindowBar
            inputTokens={state.input_tokens ?? 0}
            outputTokens={state.output_tokens ?? 0}
            cacheReadTokens={state.cache_read_tokens ?? 0}
            cacheCreationTokens={state.cache_creation_tokens ?? 0}
            compact
          />
        </div>
      )}

      {/* ── Main content area ── */}
      <div className="monitor-card-body">
        {mode === 'monitor' ? (
          <>
            {/* Status line */}
            <div className="monitor-detail">
              <span className="detail-label">Status</span>
              <span className="detail-value">{getStatusLabel(state)}</span>
            </div>

            {/* Counters */}
            <div style={{ display: 'flex', gap: 'var(--space-lg)' }}>
              <div className="monitor-detail" style={{ flex: 1 }}>
                <span className="detail-label">Messages</span>
                <span className="detail-value mono">{state?.message_count ?? 0}</span>
              </div>
              <div className="monitor-detail" style={{ flex: 1 }}>
                <span className="detail-label">Tool Calls</span>
                <span className="detail-value mono">{totalToolCalls}</span>
              </div>
            </div>

          </>
        ) : (
          <div style={{ minHeight: 300, display: 'flex', flexDirection: 'column', flex: 1 }}>
            <EmbeddedTerminal sessionId={sessionId} projectPath={session.project_path} />
          </div>
        )}
      </div>
    </div>
  );
};
