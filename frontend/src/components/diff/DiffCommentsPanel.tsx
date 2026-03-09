import React, { useState } from 'react';
import type { DiffComment } from '@/types/generated';
import { api } from '@/api/client';

interface DiffCommentsPanelProps {
  comments: DiffComment[];
  filePath: string;
  onAddComment: (comment: DiffComment) => void;
  sessionId?: string | null;
  onTerminalLaunched?: () => void;
  lineNumber?: string;
  onLineNumberChange?: (value: string) => void;
  onScrollToLine?: (lineNum: number) => void;
}

function formatCommentsAsChangeRequest(comments: DiffComment[], filePath: string): string {
  if (comments.length === 0) return '';
  const lines = [`Change requests for ${filePath}:\n`];
  for (const c of comments) {
    lines.push(`- Line ${c.line_number}: ${c.text ?? ''}`);
  }
  return lines.join('\n');
}

export const DiffCommentsPanel: React.FC<DiffCommentsPanelProps> = ({
  comments,
  filePath,
  onAddComment,
  sessionId,
  onTerminalLaunched,
  lineNumber: externalLineNumber,
  onLineNumberChange,
  onScrollToLine,
}) => {
  const [newComment, setNewComment] = useState('');
  const lineNumber = externalLineNumber ?? '';
  const setLineNumber = onLineNumberChange ?? (() => {});
  const [copied, setCopied] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [collapsed, setCollapsed] = useState(false);

  const fileComments = comments.filter((c) => c.file_path === filePath);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!newComment.trim() || !lineNumber) return;

    const comment: DiffComment = {
      id: `comment-${Date.now()}`,
      timestamp: new Date().toISOString(),
      file_path: filePath,
      line_number: parseInt(lineNumber, 10),
      side: 'unified',
      text: newComment.trim(),
    };

    onAddComment(comment);
    setNewComment('');
    setLineNumber('');
  };

  const handleCopyChangeRequest = async () => {
    const text = formatCommentsAsChangeRequest(fileComments, filePath);
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Fallback: select from hidden textarea
    }
  };

  const handleSubmitAsPrompt = async () => {
    if (!sessionId || fileComments.length === 0) return;
    const prompt = formatCommentsAsChangeRequest(fileComments, filePath);
    if (!prompt) return;
    setSubmitting(true);
    try {
      await api.terminal.launch({
        session_id: sessionId,
        resume: true,
        prompt,
      });
      onTerminalLaunched?.();
    } catch {
      // Launch failed — user can retry
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className={`diff-comments-panel ${collapsed ? 'collapsed' : ''}`}>
      <div
        className="diff-comments-header"
        onClick={() => setCollapsed(!collapsed)}
        style={{ cursor: 'pointer' }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-sm)' }}>
          <svg
            width="10"
            height="10"
            viewBox="0 0 10 10"
            fill="currentColor"
            style={{
              transform: collapsed ? 'rotate(-90deg)' : 'rotate(0deg)',
              transition: 'transform 0.15s',
            }}
          >
            <path d="M2 3l3 4 3-4H2z" />
          </svg>
          <h4>Comments</h4>
          <span className="comments-count">{fileComments.length}</span>
        </div>
        <div
          style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-sm)' }}
          onClick={(e) => e.stopPropagation()}
        >
          {fileComments.length > 0 && (
            <>
              <button
                className="btn btn-ghost btn-xs"
                onClick={handleCopyChangeRequest}
                title="Copy all comments as a change request to paste into the session"
              >
                {copied ? 'Copied' : 'Copy as prompt'}
              </button>
              {sessionId && (
                <button
                  className="btn btn-primary btn-xs"
                  onClick={handleSubmitAsPrompt}
                  disabled={submitting}
                  title="Submit comments as a prompt in the active session terminal"
                >
                  {submitting ? 'Submitting...' : 'Submit as prompt'}
                </button>
              )}
            </>
          )}
        </div>
      </div>

      {!collapsed && (
        <>
          <div className="diff-comments-list">
            {fileComments.length === 0 ? (
              <div className="comments-empty">
                <p>No comments on this file</p>
              </div>
            ) : (
              fileComments.map((comment) => (
                <div
                  key={comment.id ?? comment.timestamp}
                  className="diff-comment"
                  onClick={() => onScrollToLine?.(comment.line_number)}
                  style={{ cursor: 'pointer' }}
                >
                  <div className="comment-header">
                    <span className="comment-author">You</span>
                    <span className="comment-line">Line {comment.line_number}</span>
                    <span className="comment-time">
                      {new Date(comment.timestamp).toLocaleString()}
                    </span>
                  </div>
                  <div className="comment-body">{comment.text ?? ''}</div>
                </div>
              ))
            )}
          </div>

          <form className="diff-comment-form" onSubmit={handleSubmit}>
            <div className="comment-form-row">
              <input
                type="number"
                placeholder="Line #"
                value={lineNumber}
                onChange={(e) => setLineNumber(e.target.value)}
                className="comment-line-input"
                min="1"
              />
              <input
                type="text"
                placeholder="Add a comment..."
                value={newComment}
                onChange={(e) => setNewComment(e.target.value)}
                className="comment-text-input"
              />
              <button
                type="submit"
                className="btn btn-primary btn-sm"
                disabled={!newComment.trim() || !lineNumber}
              >
                Add
              </button>
            </div>
          </form>
        </>
      )}
    </div>
  );
};
