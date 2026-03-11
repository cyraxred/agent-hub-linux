import React, { useState, useRef, useEffect } from 'react';
import type { SessionMonitorState } from '@/types/generated';
import { useSessionsStore, type TaggedSession } from '@/store/sessions';
import { useHiddenSessionsStore } from '@/store/hiddenSessions';
import { SessionId } from '@/types/session';

interface SessionRowProps {
  session: TaggedSession;
  isSelected: boolean;
  isMonitored: boolean;
  onClick: () => void;
  onDoubleClick: () => void;
  monitorState?: SessionMonitorState;
  /** If true, the row is in "show hidden" mode — show Unhide instead of Hide */
  isHiddenView?: boolean;
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
  session: TaggedSession,
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
  isHiddenView = false,
}) => {
  const customName = useSessionsStore((s) => s.customSessionNames[session.id]);
  const setSessionName = useSessionsStore((s) => s.setSessionName);
  const deleteSession = useSessionsStore((s) => s.deleteSession);
  const hide = useHiddenSessionsStore((s) => s.hide);
  const unhide = useHiddenSessionsStore((s) => s.unhide);

  const [renaming, setRenaming] = useState(false);
  const [renameValue, setRenameValue] = useState('');
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [hovered, setHovered] = useState(false);
  const renameRef = useRef<HTMLInputElement>(null);

  const dotColor = getStatusDotColor(session, isMonitored, monitorState);
  const displayName = customName || session.slug || SessionId.rawId(session.id).slice(0, 8);
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

  const handleHide = (e: React.MouseEvent) => {
    e.stopPropagation();
    hide(SessionId.rawId(session.id));
  };

  const handleUnhide = (e: React.MouseEvent) => {
    e.stopPropagation();
    unhide(SessionId.rawId(session.id));
  };

  const handleDeleteClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    setConfirmDelete(true);
  };

  const handleDeleteConfirm = (e: React.MouseEvent) => {
    e.stopPropagation();
    deleteSession(session.id);
  };

  const handleDeleteCancel = (e: React.MouseEvent) => {
    e.stopPropagation();
    setConfirmDelete(false);
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
      <div
        className="session-row-left"
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => { setHovered(false); setConfirmDelete(false); }}
      >
        <div className="session-status-indicator">
          <span className="status-dot" style={{ backgroundColor: dotColor }} />
        </div>
        <div className="session-row-info">
          {/* Title row: name + rename btn always here */}
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
              placeholder={SessionId.rawId(session.id).slice(0, 8)}
            />
          ) : (
            <span className="session-title-row">
              <span className="session-title" onDoubleClick={handleStartRename}>
                {displayName}
              </span>
              <button className="session-rename-btn" onClick={handleStartRename} title="Rename session">
                <svg width="11" height="11" viewBox="0 0 16 16" fill="currentColor">
                  <path d="M11.013 1.427a1.75 1.75 0 012.474 0l1.086 1.086a1.75 1.75 0 010 2.474l-8.61 8.61c-.21.21-.47.364-.756.445l-3.251.93a.75.75 0 01-.927-.928l.929-3.25c.081-.286.235-.547.445-.758l8.61-8.61zm1.414 1.06a.25.25 0 00-.354 0L3.462 11.1a.25.25 0 00-.064.108l-.631 2.208 2.208-.63a.25.25 0 00.108-.064l8.61-8.61a.25.25 0 000-.354l-1.086-1.086z" />
                </svg>
              </button>
            </span>
          )}

          {/* Meta row: slug OR action buttons on hover */}
          <div className="session-meta-row">
            {hovered && !renaming ? (
              <span className="session-actions">
                {confirmDelete ? (
                  <>
                    <span className="session-delete-confirm">Delete?</span>
                    <button className="session-action-btn" onClick={handleDeleteConfirm} title="Confirm" style={{ color: 'var(--accent-red, #ff7b72)' }}>Yes</button>
                    <button className="session-action-btn" onClick={handleDeleteCancel} title="Cancel">No</button>
                  </>
                ) : (
                  <>
                    {isHiddenView ? (
                      <button className="session-action-btn" onClick={handleUnhide} title="Unhide session">
                        <svg width="13" height="13" viewBox="0 0 16 16" fill="currentColor">
                          <path d="M8 2c1.981 0 3.671.992 4.933 2.078 1.27 1.091 2.187 2.345 2.637 3.023a1.62 1.62 0 010 1.798c-.45.678-1.367 1.932-2.637 3.023C11.67 13.008 9.981 14 8 14c-1.981 0-3.671-.992-4.933-2.078C1.797 10.83.88 9.576.43 8.898a1.62 1.62 0 010-1.798c.45-.677 1.367-1.931 2.637-3.022C4.33 2.992 6.019 2 8 2zm0 1.5a6.501 6.501 0 100 13 6.501 6.501 0 000-13zM8 5.5a2.5 2.5 0 110 5 2.5 2.5 0 010-5z" />
                        </svg>
                      </button>
                    ) : (
                      <button className="session-action-btn" onClick={handleHide} title="Hide session">
                        <svg width="13" height="13" viewBox="0 0 16 16" fill="currentColor">
                          <path d="M.143 2.31a.75.75 0 011.047-.167l14.5 10.5a.75.75 0 11-.88 1.214l-2.248-1.628C11.346 13.19 9.792 14 8 14c-1.981 0-3.671-.992-4.933-2.078C1.797 10.83.88 9.576.43 8.898a1.62 1.62 0 010-1.798c.346-.522.885-1.26 1.614-2.008L.31 3.357A.75.75 0 01.143 2.31zm2.614 3.44a12.422 12.422 0 00-1.712 2.01.12.12 0 000 .135c.435.658 1.248 1.783 2.392 2.737C4.627 11.392 6.145 12.25 8 12.25c1.26 0 2.467-.49 3.48-1.138L9.4 9.768a2.5 2.5 0 01-3.168-3.168L2.757 5.75zm5.973-1.457a2.5 2.5 0 012.475 2.475l-2.475-2.475zM8 3.75c-1.26 0-2.467.49-3.48 1.138l1.02.739.005.003 1.036.75A2.5 2.5 0 0110.25 8l.001.048 1.787 1.293C13.203 8.558 14 7.32 14.287 6.897a.12.12 0 000-.135C13.852 6.104 13.04 4.98 11.895 4.026 10.873 3.108 9.355 2.25 8 2.25z" />
                        </svg>
                      </button>
                    )}
                    <button className="session-action-btn session-delete-btn" onClick={handleDeleteClick} title="Delete session">
                      <svg width="13" height="13" viewBox="0 0 16 16" fill="currentColor">
                        <path d="M11 1.75V3h2.25a.75.75 0 010 1.5H2.75a.75.75 0 010-1.5H5V1.75C5 .784 5.784 0 6.75 0h2.5C10.216 0 11 .784 11 1.75zm-4.5 0V3h5V1.75a.25.25 0 00-.25-.25h-4.5a.25.25 0 00-.25.25zM4.997 6.178a.75.75 0 10-1.493.144L4.916 14H11.08l1.413-7.678a.75.75 0 00-1.493-.144L9.706 13H6.29L4.997 6.178z" />
                      </svg>
                    </button>
                  </>
                )}
              </span>
            ) : (
              firstMessagePreview && (
                <span className="session-branch">{firstMessagePreview}</span>
              )
            )}
            {!hovered && (
              <span className="session-time">
                {formatRelativeTime(session.last_activity_at)}
              </span>
            )}
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
