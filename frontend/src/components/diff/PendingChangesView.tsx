import { SessionId } from '@/types/session';
import React, { useEffect, useState, useCallback, useRef } from 'react';
import { useGitStore } from '@/store/git';
import { api } from '@/api/client';
import { DiffCommentsPanel } from './DiffCommentsPanel';
import type { DiffComment } from '@/types/generated';

interface PendingChangesViewProps {
  repoPath: string;
  sessionId?: SessionId | null;
  onTerminalLaunched?: () => void;
}

export const PendingChangesView: React.FC<PendingChangesViewProps> = ({ repoPath, sessionId, onTerminalLaunched }) => {
  const {
    files,
    comments,
    selectedFile,
    diffMode,
    loading,
    error,
    fetchDiff,
    selectFile,
    addComment,
  } = useGitStore();

  const [unifiedDiff, setUnifiedDiff] = useState<string>('');
  const [diffLoading, setDiffLoading] = useState(false);
  const [commentLineNumber, setCommentLineNumber] = useState('');
  const diffContentRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    fetchDiff(repoPath, diffMode);
  }, [repoPath, diffMode, fetchDiff]);

  // Fetch unified diff for selected file
  const loadFileDiff = useCallback(async () => {
    if (!selectedFile) {
      setUnifiedDiff('');
      return;
    }
    setDiffLoading(true);
    try {
      const text = await api.git.unifiedDiff(repoPath, diffMode);
      setUnifiedDiff(text);
    } catch {
      setUnifiedDiff('');
    } finally {
      setDiffLoading(false);
    }
  }, [selectedFile, repoPath, diffMode]);

  useEffect(() => {
    loadFileDiff();
  }, [loadFileDiff]);

  const totalAdditions = files.reduce((sum, f) => sum + (f.additions ?? 0), 0);
  const totalDeletions = files.reduce((sum, f) => sum + (f.deletions ?? 0), 0);

  const handleAddComment = (comment: DiffComment) => {
    addComment(comment);
  };

  const handleDiffLineClick = (lineNum: number | null) => {
    if (lineNum != null) {
      setCommentLineNumber(String(lineNum));
    }
  };

  const handleScrollToLine = (lineNum: number) => {
    const container = diffContentRef.current;
    if (!container) return;
    const row = container.querySelector(`tr[data-line-new="${lineNum}"], tr[data-line-old="${lineNum}"]`);
    if (row) {
      row.scrollIntoView({ behavior: 'smooth', block: 'center' });
      row.classList.add('diff-line-highlight');
      setTimeout(() => row.classList.remove('diff-line-highlight'), 1500);
    }
  };

  if (loading) {
    return (
      <div className="pending-changes loading">
        <div className="spinner" />
        <p>Loading changes...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="pending-changes error-state">
        <svg width="24" height="24" viewBox="0 0 16 16" fill="currentColor">
          <path d="M6.457 1.047c.659-1.234 2.427-1.234 3.086 0l6.082 11.378A1.75 1.75 0 0114.082 15H1.918a1.75 1.75 0 01-1.543-2.575zM8 5a.75.75 0 00-.75.75v2.5a.75.75 0 001.5 0v-2.5A.75.75 0 008 5zm1 6a1 1 0 11-2 0 1 1 0 012 0z" />
        </svg>
        <p>{error}</p>
        <button className="btn btn-secondary" onClick={() => fetchDiff(repoPath, diffMode)}>
          Retry
        </button>
      </div>
    );
  }

  if (files.length === 0) {
    return (
      <div className="pending-changes empty-state">
        <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1">
          <path d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
        <h3>No Pending Changes</h3>
        <p>This repository has no uncommitted file changes.</p>
      </div>
    );
  }

  return (
    <div className="pending-changes">
      {/* Header with summary stats */}
      <div className="changes-header">
        <div className="changes-summary">
          <span className="changes-count">
            {files.length} file{files.length !== 1 ? 's' : ''} changed
          </span>
          <span className="changes-additions">+{totalAdditions}</span>
          <span className="changes-deletions">-{totalDeletions}</span>
        </div>
      </div>

      {/* Two-pane layout */}
      <div className="changes-body">
        {/* Left: file list */}
        <div className="changes-file-list">
          {files.map((file) => (
            <div
              key={file.file_path}
              className={`changes-file-item ${selectedFile === file.file_path ? 'selected' : ''}`}
              onClick={() => selectFile(file.file_path)}
            >
              <div className="diff-compact">
                <div className="diff-file-header-compact">
                  <span className="diff-file-path">{file.relative_path || file.file_path}</span>
                  <span className="diff-stats">
                    {(file.additions ?? 0) > 0 && (
                      <span className="diff-additions">+{file.additions}</span>
                    )}
                    {(file.deletions ?? 0) > 0 && (
                      <span className="diff-deletions">-{file.deletions}</span>
                    )}
                  </span>
                </div>
              </div>
            </div>
          ))}
        </div>

        {/* Right: selected file diff + comments */}
        <div className="changes-detail-wrapper">
          <div className="changes-detail">
            {selectedFile ? (
              <div className="diff-view">
                <div className="diff-file-header">
                  <div className="diff-file-info">
                    <span className="diff-file-path">{selectedFile}</span>
                  </div>
                  <div className="diff-file-stats">
                    {(() => {
                      const f = files.find((x) => x.file_path === selectedFile);
                      if (!f) return null;
                      return (
                        <>
                          {(f.additions ?? 0) > 0 && (
                            <span className="diff-additions">+{f.additions}</span>
                          )}
                          {(f.deletions ?? 0) > 0 && (
                            <span className="diff-deletions">-{f.deletions}</span>
                          )}
                        </>
                      );
                    })()}
                  </div>
                </div>
                <div className="diff-content" ref={diffContentRef}>
                  {diffLoading ? (
                    <div style={{ padding: 'var(--space-lg)', textAlign: 'center' }}>
                      <div className="spinner" />
                    </div>
                  ) : (
                    <table className="diff-table">
                      <tbody>
                        {parseDiffLines(unifiedDiff).map((line, i) => (
                          <tr
                            key={i}
                            className={`diff-line diff-line-${line.type}`}
                            data-line-new={line.newNum ?? undefined}
                            data-line-old={line.oldNum ?? undefined}
                            onClick={() => handleDiffLineClick(line.newNum ?? line.oldNum)}
                            style={{ cursor: 'pointer' }}
                          >
                            <td className="diff-line-num old">{line.oldNum ?? ''}</td>
                            <td className="diff-line-num new">{line.newNum ?? ''}</td>
                            <td className="diff-line-prefix">{line.prefix}</td>
                            <td className="diff-line-content">
                              <pre>{line.content}</pre>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </div>
              </div>
            ) : (
              <div className="changes-detail-empty">
                <p>Select a file to view changes</p>
              </div>
            )}
          </div>
          {selectedFile && (
            <DiffCommentsPanel
              comments={comments}
              filePath={selectedFile}
              onAddComment={handleAddComment}
              sessionId={sessionId}
              onTerminalLaunched={onTerminalLaunched}
              lineNumber={commentLineNumber}
              onLineNumberChange={setCommentLineNumber}
              onScrollToLine={handleScrollToLine}
            />
          )}
        </div>
      </div>
    </div>
  );
};

interface DiffLineInfo {
  type: 'add' | 'del' | 'context' | 'hunk';
  prefix: string;
  content: string;
  oldNum: number | null;
  newNum: number | null;
}

function parseDiffLines(unified: string): DiffLineInfo[] {
  if (!unified) return [];

  const lines = unified.split('\n');
  const result: DiffLineInfo[] = [];
  let oldNum = 0;
  let newNum = 0;

  for (const line of lines) {
    if (line.startsWith('@@')) {
      const match = line.match(/@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/);
      if (match && match[1] && match[2]) {
        oldNum = parseInt(match[1], 10);
        newNum = parseInt(match[2], 10);
      }
      result.push({ type: 'hunk', prefix: '', content: line, oldNum: null, newNum: null });
    } else if (line.startsWith('+')) {
      result.push({ type: 'add', prefix: '+', content: line.slice(1), oldNum: null, newNum: newNum });
      newNum++;
    } else if (line.startsWith('-')) {
      result.push({ type: 'del', prefix: '-', content: line.slice(1), oldNum: oldNum, newNum: null });
      oldNum++;
    } else if (line.startsWith(' ') || line === '') {
      result.push({ type: 'context', prefix: ' ', content: line.slice(1) || '', oldNum: oldNum, newNum: newNum });
      oldNum++;
      newNum++;
    }
  }

  return result;
}
