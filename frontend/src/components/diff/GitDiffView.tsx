import React, { useEffect, useState, useCallback } from 'react';
import { useGitStore } from '@/store/git';
import { api } from '@/api/client';
import type { DiffMode } from '@/types/generated';

interface GitDiffViewProps {
  repoPath: string;
}

const DIFF_MODES: { value: DiffMode; label: string }[] = [
  { value: 'unstaged', label: 'Unstaged' },
  { value: 'staged', label: 'Staged' },
  { value: 'branch', label: 'Branch' },
];

export const GitDiffView: React.FC<GitDiffViewProps> = ({ repoPath }) => {
  const {
    files,
    selectedFile,
    diffMode,
    loading,
    error,
    fetchDiff,
    selectFile,
    setMode,
  } = useGitStore();

  const [unifiedDiff, setUnifiedDiff] = useState<string>('');
  const [diffLoading, setDiffLoading] = useState(false);

  // Fetch file list when mode or repo changes
  useEffect(() => {
    fetchDiff(repoPath, diffMode);
  }, [repoPath, diffMode, fetchDiff]);

  // Fetch unified diff for selected file
  const loadUnifiedDiff = useCallback(async () => {
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
    loadUnifiedDiff();
  }, [loadUnifiedDiff]);

  const handleModeChange = (mode: DiffMode) => {
    setMode(mode);
  };

  if (loading) {
    return (
      <div className="pending-changes loading">
        <div className="spinner" />
        <p>Loading diff...</p>
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

  return (
    <div className="pending-changes">
      {/* Mode selector */}
      <div className="changes-header">
        <div className="changes-summary">
          <div className="provider-segments">
            {DIFF_MODES.map(({ value, label }) => (
              <button
                key={value}
                className={`provider-segment ${diffMode === value ? 'active' : ''}`}
                onClick={() => handleModeChange(value)}
              >
                {label}
              </button>
            ))}
          </div>
          <span className="changes-count">
            {files.length} file{files.length !== 1 ? 's' : ''} changed
          </span>
        </div>
      </div>

      <div className="changes-body">
        {/* File list */}
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

        {/* Unified diff content */}
        <div className="changes-detail">
          {selectedFile ? (
            <div className="diff-view">
              <div className="diff-file-header">
                <div className="diff-file-info">
                  <span className="diff-file-path">{selectedFile}</span>
                </div>
              </div>
              <div className="diff-content">
                {diffLoading ? (
                  <div style={{ padding: 'var(--space-lg)', textAlign: 'center' }}>
                    <div className="spinner" />
                  </div>
                ) : (
                  <table className="diff-table">
                    <tbody>
                      {parseDiffLines(unifiedDiff).map((line, i) => (
                        <tr key={i} className={`diff-line diff-line-${line.type}`}>
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
      // Parse hunk header: @@ -oldStart,oldCount +newStart,newCount @@
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
    // Skip lines starting with "diff ", "index ", "--- ", "+++ "
  }

  return result;
}
