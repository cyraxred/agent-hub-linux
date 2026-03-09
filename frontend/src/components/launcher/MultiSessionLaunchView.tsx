import React, { useEffect, useState } from 'react';
import { useSessionsStore } from '@/store/sessions';
import { useProvidersStore } from '@/store/providers';
import { api } from '@/api/client';
import { CreateWorktreeSheet } from './CreateWorktreeSheet';

const ADD_NEW_SENTINEL = '__add_new__';

interface LaunchConfig {
  repoPath: string;
  provider: string;
  prompt: string;
  branch: string;
  useWorktree: boolean;
  attachedFiles: string[];
}

interface MultiSessionLaunchViewProps {
  onLaunched?: () => void;
}

export const MultiSessionLaunchView: React.FC<MultiSessionLaunchViewProps> = ({ onLaunched }) => {
  const repositories = useSessionsStore((s) => s.repositories);
  const selectedRepositoryPath = useSessionsStore((s) => s.selectedRepositoryPath);
  const addRepository = useSessionsStore((s) => s.addRepository);
  const fetchRepositories = useSessionsStore((s) => s.fetchRepositories);
  const selectSession = useSessionsStore((s) => s.selectSession);
  const { providers, fetchProviders } = useProvidersStore();

  useEffect(() => {
    fetchProviders();
  }, [fetchProviders]);

  const defaultProvider = providers.find((p) => p.available)?.key ?? 'claude';

  const [configs, setConfigs] = useState<LaunchConfig[]>([
    {
      repoPath: selectedRepositoryPath ?? '',
      provider: defaultProvider,
      prompt: '',
      branch: '',
      useWorktree: false,
      attachedFiles: [],
    },
  ]);
  const [showWorktreeSheet, setShowWorktreeSheet] = useState(false);
  const [worktreeRepoPath, setWorktreeRepoPath] = useState<string>('');
  const [worktreeConfigIndex, setWorktreeConfigIndex] = useState<number | null>(null);
  const [launching, setLaunching] = useState(false);
  const [launchSuccess, setLaunchSuccess] = useState(false);
  const [addRepoIndex, setAddRepoIndex] = useState<number | null>(null);
  const [newRepoPath, setNewRepoPath] = useState('');
  const [addingRepo, setAddingRepo] = useState(false);
  const [addRepoError, setAddRepoError] = useState<string | null>(null);

  const updateConfig = (index: number, updates: Partial<LaunchConfig>) => {
    setConfigs((prev) =>
      prev.map((config, i) => (i === index ? { ...config, ...updates } : config))
    );
  };

  const addConfig = () => {
    setConfigs((prev) => [
      ...prev,
      {
        repoPath: selectedRepositoryPath ?? repositories[0]?.path ?? '',
        provider: defaultProvider,
        prompt: '',
        branch: '',
        useWorktree: false,
        attachedFiles: [],
      },
    ]);
  };

  const removeConfig = (index: number) => {
    setConfigs((prev) => prev.filter((_, i) => i !== index));
  };

  const handleRepoSelectChange = (index: number, value: string) => {
    if (value === ADD_NEW_SENTINEL) {
      setAddRepoIndex(index);
      setNewRepoPath('');
      setAddRepoError(null);
    } else {
      updateConfig(index, { repoPath: value });
    }
  };

  const handleAddRepo = async () => {
    const trimmed = newRepoPath.trim();
    if (!trimmed) return;
    setAddingRepo(true);
    setAddRepoError(null);
    try {
      await addRepository(trimmed);
      if (addRepoIndex !== null) {
        updateConfig(addRepoIndex, { repoPath: trimmed });
      }
      setAddRepoIndex(null);
      setNewRepoPath('');
    } catch (err) {
      setAddRepoError((err as Error).message);
    } finally {
      setAddingRepo(false);
    }
  };

  const handleCancelAddRepo = () => {
    setAddRepoIndex(null);
    setNewRepoPath('');
    setAddRepoError(null);
  };

  const handleLaunch = async () => {
    setLaunching(true);
    try {
      // Snapshot existing session IDs before launch so we can detect the new one
      const existingIds = new Set(
        repositories.flatMap((r) =>
          (r.worktrees ?? []).flatMap((wt) => (wt.sessions ?? []).map((s) => s.id)),
        ),
      );

      for (const config of configs) {
        if (!config.repoPath) continue;
        let prompt = config.prompt.trim();
        if (config.attachedFiles.length > 0) {
          const fileList = config.attachedFiles.map((f) => `- ${f}`).join('\n');
          const prefix = `Please read and consider these files:\n${fileList}\n\n`;
          prompt = prefix + prompt;
        }
        await api.terminal.launch({
          command: config.provider,
          project_path: config.repoPath,
          prompt: prompt || undefined,
        });
      }

      // Poll for the new session to appear (up to 15s)
      const launchedPaths = new Set(validConfigs.map((c) => c.repoPath));
      const deadline = Date.now() + 15000;
      let found: string | null = null;
      while (Date.now() < deadline && !found) {
        await new Promise((r) => setTimeout(r, 1000));
        await fetchRepositories();
        const repos = useSessionsStore.getState().repositories;
        for (const repo of repos) {
          for (const wt of repo.worktrees ?? []) {
            if (!launchedPaths.has(wt.path) && !launchedPaths.has(repo.path)) continue;
            for (const session of wt.sessions ?? []) {
              if (!existingIds.has(session.id)) {
                found = session.id;
                break;
              }
            }
            if (found) break;
          }
          if (found) break;
        }
      }

      if (found) {
        selectSession(found);
        onLaunched?.();
      } else {
        setLaunchSuccess(true);
        setTimeout(() => setLaunchSuccess(false), 4000);
      }
    } finally {
      setLaunching(false);
    }
  };

  const validConfigs = configs.filter((c) => c.repoPath);

  return (
    <div className="multi-launch-view">
      <div className="launch-header">
        <h2>Launch Sessions</h2>
        <p className="launch-description">
          Configure and launch one or more agent sessions simultaneously. Each session runs in
          its own process with optional git worktree isolation.
        </p>
      </div>

      {launchSuccess && (
        <div className="launch-success-banner">
          Session{validConfigs.length !== 1 ? 's' : ''} launched — select from the sidebar to view the terminal.
        </div>
      )}

      {/* Session Configurations */}
      <div className="launch-section">
        <div className="launch-section-header">
          <h3>Session Configurations</h3>
          <button className="btn btn-secondary btn-sm" onClick={addConfig}>
            Add Session
          </button>
        </div>

        <div className="launch-configs">
          {configs.map((config, index) => (
            <div key={index} className="launch-config-card">
              <div className="config-card-header">
                <span className="config-number">Session {index + 1}</span>
                {configs.length > 1 && (
                  <button className="btn btn-ghost btn-xs" onClick={() => removeConfig(index)}>
                    Remove
                  </button>
                )}
              </div>

              <div className="config-fields">
                {/* Repository picker */}
                <div className="config-field">
                  <label>Repository</label>
                  {addRepoIndex === index ? (
                    <div className="add-repo-inline">
                      <input
                        type="text"
                        className="setting-input"
                        placeholder="/path/to/repository"
                        value={newRepoPath}
                        onChange={(e) => setNewRepoPath(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') handleAddRepo();
                          if (e.key === 'Escape') handleCancelAddRepo();
                        }}
                        autoFocus
                        disabled={addingRepo}
                      />
                      <button
                        className="btn btn-primary btn-sm"
                        onClick={handleAddRepo}
                        disabled={!newRepoPath.trim() || addingRepo}
                      >
                        {addingRepo ? 'Adding...' : 'Add'}
                      </button>
                      <button className="btn btn-ghost btn-sm" onClick={handleCancelAddRepo}>
                        Cancel
                      </button>
                      {addRepoError && (
                        <span className="text-error" style={{ fontSize: 'var(--font-size-xs)' }}>
                          {addRepoError}
                        </span>
                      )}
                    </div>
                  ) : (
                    <select
                      className="setting-select"
                      value={config.repoPath}
                      onChange={(e) => handleRepoSelectChange(index, e.target.value)}
                    >
                      <option value="">Select repository...</option>
                      {repositories.map((repo) => (
                        <option key={repo.path} value={repo.path}>
                          {repo.name} ({repo.path})
                        </option>
                      ))}
                      <option value={ADD_NEW_SENTINEL}>+ Add new repository...</option>
                    </select>
                  )}
                </div>

                {/* Provider select */}
                <div className="config-field-row">
                  <div className="config-field">
                    <label>Provider</label>
                    <div className="provider-radio-group">
                      {providers.map((p) => (
                        <label
                          key={p.key}
                          className={`provider-radio ${config.provider === p.key ? 'active' : ''} ${!p.available ? 'disabled' : ''}`}
                          title={p.available ? p.label : `${p.label} CLI not found`}
                        >
                          <input
                            type="radio"
                            name={`provider-${index}`}
                            value={p.key}
                            checked={config.provider === p.key}
                            onChange={() => updateConfig(index, { provider: p.key })}
                            disabled={!p.available}
                          />
                          <span className="provider-radio-label">{p.label}</span>
                        </label>
                      ))}
                    </div>
                  </div>
                </div>

                {/* Prompt textarea */}
                <div className="config-field">
                  <label>Prompt</label>
                  <textarea
                    className="config-textarea"
                    placeholder="Describe the task for the agent..."
                    value={config.prompt}
                    onChange={(e) => updateConfig(index, { prompt: e.target.value })}
                    rows={3}
                  />
                </div>

                {/* Attached files */}
                <div className="config-field">
                  <label>Attach Files</label>
                  <div className="attached-files">
                    {config.attachedFiles.map((filePath, fileIdx) => (
                      <div key={fileIdx} className="attached-file-chip">
                        <span className="attached-file-path">{filePath}</span>
                        <button
                          className="attached-file-remove"
                          onClick={() => {
                            updateConfig(index, {
                              attachedFiles: config.attachedFiles.filter((_, i) => i !== fileIdx),
                            });
                          }}
                          title="Remove file"
                        >
                          <svg width="10" height="10" viewBox="0 0 16 16" fill="currentColor">
                            <path d="M3.72 3.72a.75.75 0 011.06 0L8 6.94l3.22-3.22a.749.749 0 011.275.326.749.749 0 01-.215.734L9.06 8l3.22 3.22a.749.749 0 01-.326 1.275.749.749 0 01-.734-.215L8 9.06l-3.22 3.22a.751.751 0 01-1.042-.018.751.751 0 01-.018-1.042L6.94 8 3.72 4.78a.75.75 0 010-1.06z" />
                          </svg>
                        </button>
                      </div>
                    ))}
                    <input
                      type="text"
                      className="setting-input attached-file-input"
                      placeholder="Type file path and press Enter..."
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') {
                          const val = (e.target as HTMLInputElement).value.trim();
                          if (val) {
                            updateConfig(index, {
                              attachedFiles: [...config.attachedFiles, val],
                            });
                            (e.target as HTMLInputElement).value = '';
                          }
                          e.preventDefault();
                        }
                      }}
                    />
                  </div>
                </div>

                {/* Branch input + worktree toggle */}
                <div className="config-field-row">
                  <div className="config-field">
                    <label>Branch</label>
                    <input
                      type="text"
                      className="setting-input"
                      placeholder="main"
                      value={config.branch}
                      onChange={(e) => updateConfig(index, { branch: e.target.value })}
                    />
                  </div>
                  <div className="config-field">
                    <label>Worktree</label>
                    <div className="worktree-toggle">
                      <label className="toggle-switch">
                        <input
                          type="checkbox"
                          checked={config.useWorktree}
                          onChange={(e) => updateConfig(index, { useWorktree: e.target.checked })}
                        />
                        <span className="toggle-slider" />
                      </label>
                      {config.useWorktree && config.repoPath && (
                        <button
                          className="btn btn-ghost btn-xs"
                          onClick={() => {
                            setWorktreeRepoPath(config.repoPath);
                            setWorktreeConfigIndex(index);
                            setShowWorktreeSheet(true);
                          }}
                        >
                          Configure
                        </button>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Launch Button */}
      <div className="launch-footer">
        <div className="launch-summary">
          {validConfigs.length > 0 ? (
            <span>
              Ready to launch {validConfigs.length} session{validConfigs.length !== 1 ? 's' : ''}
            </span>
          ) : (
            <span className="text-muted">Select a repository to launch</span>
          )}
        </div>
        <button
          className="btn btn-primary btn-lg"
          disabled={validConfigs.length === 0 || launching}
          onClick={handleLaunch}
        >
          {launching ? (
            <>
              <div className="spinner spinner-sm" />
              Launching...
            </>
          ) : (
            <>Launch {validConfigs.length > 1 ? `${validConfigs.length} Sessions` : 'Session'}</>
          )}
        </button>
      </div>

      {showWorktreeSheet && (
        <CreateWorktreeSheet
          repoPath={worktreeRepoPath}
          onClose={() => {
            setShowWorktreeSheet(false);
            setWorktreeConfigIndex(null);
          }}
          onWorktreeCreated={(_worktreePath, branch) => {
            if (worktreeConfigIndex !== null) {
              updateConfig(worktreeConfigIndex, { branch });
            }
          }}
        />
      )}
    </div>
  );
};
