import React, { useState, useEffect } from 'react';
import { useGitStore } from '@/store/git';
import { useSessionsStore } from '@/store/sessions';
import { api } from '@/api/client';
import type { RemoteBranch } from '@/types/generated';

interface CreateWorktreeSheetProps {
  repoPath: string;
  onClose: () => void;
  onWorktreeCreated?: (worktreePath: string, branch: string) => void;
}

export const CreateWorktreeSheet: React.FC<CreateWorktreeSheetProps> = ({
  repoPath,
  onClose,
  onWorktreeCreated,
}) => {
  const { branches, fetchBranches } = useGitStore();
  const repositories = useSessionsStore((s) => s.repositories);
  const fetchRepositories = useSessionsStore((s) => s.fetchRepositories);
  const [branchName, setBranchName] = useState('');
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchBranches(repoPath);
  }, [repoPath, fetchBranches]);

  // Derive existing worktrees from repository store data
  const repo = repositories.find((r) => r.path === repoPath);
  const existingWorktrees = (repo?.worktrees ?? []).map((wt) => ({
    path: wt.path,
    branch: wt.name,
    isMain: !wt.is_worktree,
    isWorktree: wt.is_worktree ?? false,
  }));

  const handleCreate = async () => {
    if (!branchName.trim()) return;
    setCreating(true);
    setError(null);

    try {
      const result = await api.git.createWorktree(repoPath, branchName.trim(), true);
      setBranchName('');
      // Refresh both branches and repositories to update the worktree list
      await Promise.all([fetchBranches(repoPath), fetchRepositories()]);
      onWorktreeCreated?.(result.worktree_path, result.branch);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setCreating(false);
    }
  };

  const handleDelete = async (worktreePath: string) => {
    setError(null);
    try {
      await api.git.deleteWorktree(worktreePath);
      // Refresh repositories to update the worktree list
      await fetchRepositories();
    } catch (err) {
      setError((err as Error).message);
    }
  };

  return (
    <div className="sheet-backdrop" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="sheet worktree-sheet">
        <div className="sheet-header">
          <h3>Git Worktrees</h3>
          <button className="btn btn-ghost btn-sm" onClick={onClose}>
            Close
          </button>
        </div>

        {error && (
          <div className="sheet-error">
            <p>{error}</p>
          </div>
        )}

        <div className="sheet-body">
          <div className="worktree-create-form">
            <h4>Create New Worktree</h4>
            <div className="worktree-form-row">
              <input
                type="text"
                className="setting-input"
                placeholder="Branch name (e.g., feature/my-feature)"
                value={branchName}
                onChange={(e) => setBranchName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') handleCreate();
                }}
                list="branch-suggestions"
              />
              <datalist id="branch-suggestions">
                {branches.map((branch: RemoteBranch) => (
                  <option key={branch.name} value={branch.name} />
                ))}
              </datalist>
              <button
                className="btn btn-primary btn-sm"
                onClick={handleCreate}
                disabled={!branchName.trim() || creating}
              >
                {creating ? 'Creating...' : 'Create'}
              </button>
            </div>
          </div>

          <div className="worktree-list">
            <h4>Existing Worktrees</h4>
            {existingWorktrees.length === 0 ? (
              <div className="worktree-empty">
                <p>No worktrees configured for this repository.</p>
              </div>
            ) : (
              <div className="worktree-items">
                {existingWorktrees.map((wt) => (
                  <div key={wt.path} className={`worktree-item ${wt.isMain ? 'main' : ''}`}>
                    <div className="worktree-item-info">
                      <div className="worktree-branch">
                        {wt.isMain && <span className="main-badge">main</span>}
                        {wt.isWorktree && <span className="worktree-badge">worktree</span>}
                        <span className="worktree-branch-name">{wt.branch}</span>
                      </div>
                      <span className="worktree-path">{wt.path}</span>
                    </div>
                    {wt.isWorktree && (
                      <button
                        className="btn btn-danger btn-xs"
                        onClick={() => handleDelete(wt.path)}
                      >
                        Delete
                      </button>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
