import React, { useState, useRef, useEffect } from 'react';
import type { CLISession, SessionMonitorState } from '@/types/generated';
import { useSessionsStore } from '@/store/sessions';

interface SessionRowProps {
  session: CLISession;
  isSelected: boolean;
  isMonitored: boolean;
  onClick: () => void;
  onDoubleClick: () => void;
  monitorState?: SessionMonitorState;
}

function formatRelativeTime(dateStr: string): string {
  const now = Date.now();
  const then = new Date(dateStr).getTime();
  const diff = now - then;

  const seconds = Math.floor(diff / 1000);
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

function truncate(text: string, maxLen: number): string {
  if (text.length <= maxLen) return text;
  return text.slice(0, maxLen).trimEnd() + '\u2026';
}

function getStatusDotColor(
  session: CLISession,
  isMonitored: boolean,
  monitorState?: SessionMonitorState,
): string {
  if (isMonitored && monitorState?.status) {
    switch (monitorState.status.kind) {
      case 'thinking':
        return 'var(--accent-purple, #a855f7)';
      case 'executing_tool':
        return 'var(--accent-blue, #58a6ff)';
      case 'waiting_for_user':
        return 'var(--accent-orange, #f97316)';
      case 'awaiting_approval':
        return 'var(--accent-yellow, #d29922)';
      case 'idle':
        return 'var(--text-tertiary, #6b7280)';
    }
  }
  return session.is_active
    ? 'var(--accent-green, #3fb950)'
    : 'var(--text-tertiary, #6b7280)';
}

export const SessionRow: React.FC<SessionRowProps> = ({
  session,
  isSelected,
  isMonitored,
  onClick,
  onDoubleClick,
  monitorState,
}) => {
  const customName = useSessionsStore((s) => s.customSessionNames[session.id]);
  const setSessionName = useSessionsStore((s) => s.setSessionName);

  const [renaming, setRenaming] = useState(false);
  const [renameValue, setRenameValue] = useState('');
  const renameRef = useRef<HTMLInputElement>(null);

  const dotColor = getStatusDotColor(session, isMonitored, monitorState);
  const displayName = customName || session.slug || session.id.slice(0, 8);
  const firstMessagePreview = session.first_message
    ? truncate(session.first_message, 50)
    : null;

  useEffect(() => {
    if (renaming && renameRef.current) {
      renameRef.current.focus();
      renameRef.current.select();
    }
  }, [renaming]);

  const handleStartRename = (e: React.MouseEvent) => {
    e.stopPropagation();
    setRenameValue(customName || session.slug || '');
    setRenaming(true);
  };

  const handleRenameSubmit = () => {
    const trimmed = renameValue.trim();
    setSessionName(session.id, trimmed || null);
    setRenaming(false);
  };

  const handleRenameCancel = () => {
    setRenaming(false);
  };

  return (
    <div
      className={`session-row ${isSelected ? 'selected' : ''}`}
      onClick={onClick}
      onDoubleClick={onDoubleClick}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          onClick();
        }
      }}
    >
      <div className="session-row-left">
        <div className="session-status-indicator">
          <span
            className="status-dot"
            style={{ backgroundColor: dotColor }}
          />
        </div>
        <div className="session-row-info">
          {renaming ? (
            <input
              ref={renameRef}
              className="session-rename-input"
              type="text"
              value={renameValue}
              onChange={(e) => setRenameValue(e.target.value)}
              onKeyDown={(e) => {
                e.stopPropagation();
                if (e.key === 'Enter') handleRenameSubmit();
                if (e.key === 'Escape') handleRenameCancel();
              }}
              onBlur={handleRenameSubmit}
              onClick={(e) => e.stopPropagation()}
              placeholder={session.id.slice(0, 8)}
            />
          ) : (
            <span className="session-title-row">
              <span className="session-title" onDoubleClick={handleStartRename}>
                {displayName}
              </span>
              <button
                className="session-rename-btn"
                onClick={handleStartRename}
                title="Rename session"
              >
                <svg width="11" height="11" viewBox="0 0 16 16" fill="currentColor">
                  <path d="M11.013 1.427a1.75 1.75 0 012.474 0l1.086 1.086a1.75 1.75 0 010 2.474l-8.61 8.61c-.21.21-.47.364-.756.445l-3.251.93a.75.75 0 01-.927-.928l.929-3.25c.081-.286.235-.547.445-.758l8.61-8.61zm1.414 1.06a.25.25 0 00-.354 0L3.462 11.1a.25.25 0 00-.064.108l-.631 2.208 2.208-.63a.25.25 0 00.108-.064l8.61-8.61a.25.25 0 000-.354l-1.086-1.086z" />
                </svg>
              </button>
            </span>
          )}
          <div className="session-meta-row">
            {firstMessagePreview && (
              <span className="session-branch">{firstMessagePreview}</span>
            )}
            <span className="session-time">
              {formatRelativeTime(session.last_activity_at)}
            </span>
          </div>
        </div>
      </div>
      <div className="session-row-right">
        {session.is_active && (
          <span className="status-badge status-running">Active</span>
        )}
        {isMonitored && (
          <span className="status-badge status-completed">Monitored</span>
        )}
      </div>
    </div>
  );
};
