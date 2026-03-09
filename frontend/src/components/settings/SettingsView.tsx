import React, { useEffect, useRef } from 'react';
import { useSettingsStore } from '@/store/settings';
import { useProvidersStore } from '@/store/providers';
import { HostsSettingsSection } from './HostsSettingsSection';

export const SettingsView: React.FC = () => {
  const { settings, loading, error, dirty, fetchSettings, updateSettings, saveSettings } =
    useSettingsStore();
  const { providers, fetchProviders } = useProvidersStore();

  const initialSettings = useRef<Record<string, unknown> | null>(null);

  useEffect(() => {
    fetchSettings();
    fetchProviders();
  }, [fetchSettings, fetchProviders]);

  // Capture initial settings once loaded so we can reset
  useEffect(() => {
    if (!dirty && Object.keys(settings).length > 0 && !initialSettings.current) {
      initialSettings.current = { ...settings };
    }
  }, [settings, dirty]);

  const handleReset = () => {
    if (initialSettings.current) {
      updateSettings(initialSettings.current);
      // Mark as not dirty by refetching
      fetchSettings();
    }
  };

  const cliCommand = (settings.cli_command as string) ?? '';
  const codexCommand = (settings.codex_command as string) ?? '';
  const approvalTimeout = (settings.approval_timeout_seconds as number) ?? 10;
  const sessionProvider = (settings.session_provider as string) ?? 'claude';
  const theme = (settings.theme as string) ?? 'dark';

  return (
    <div className="settings-view">
      <div className="settings-header">
        <h2>Settings</h2>
        <div className="settings-actions">
          {dirty && (
            <>
              <button className="btn btn-secondary" onClick={handleReset}>
                Reset
              </button>
              <button className="btn btn-primary" onClick={saveSettings} disabled={loading}>
                {loading ? 'Saving...' : 'Save'}
              </button>
            </>
          )}
        </div>
      </div>

      {error && (
        <div className="settings-error">
          <p>{error}</p>
        </div>
      )}

      <div className="settings-sections">
        {/* CLI Commands */}
        <div className="settings-section">
          <h3>CLI Commands</h3>
          <div className="settings-group">
            <div className="setting-row">
              <div className="setting-info">
                <label className="setting-label">Claude CLI Command</label>
                <span className="setting-description">Command used to launch Claude Code sessions</span>
              </div>
              <input
                type="text"
                className="setting-input"
                value={cliCommand}
                onChange={(e) => updateSettings({ cli_command: e.target.value })}
                placeholder="claude"
              />
            </div>
            <div className="setting-row">
              <div className="setting-info">
                <label className="setting-label">Codex CLI Command</label>
                <span className="setting-description">Command used to launch Codex sessions</span>
              </div>
              <input
                type="text"
                className="setting-input"
                value={codexCommand}
                onChange={(e) => updateSettings({ codex_command: e.target.value })}
                placeholder="codex"
              />
            </div>
          </div>
        </div>

        {/* Session Behavior */}
        <div className="settings-section">
          <h3>Session Behavior</h3>
          <div className="settings-group">
            <div className="setting-row">
              <div className="setting-info">
                <label className="setting-label">Approval Timeout</label>
                <span className="setting-description">
                  Seconds to wait before auto-approving tool calls (0 = never auto-approve)
                </span>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-sm)' }}>
                <input
                  type="range"
                  min={0}
                  max={30}
                  step={1}
                  value={approvalTimeout}
                  onChange={(e) =>
                    updateSettings({ approval_timeout_seconds: parseInt(e.target.value, 10) })
                  }
                  style={{ width: 120 }}
                />
                <span
                  className="setting-label"
                  style={{ fontFamily: 'var(--font-mono)', minWidth: 28, textAlign: 'right' }}
                >
                  {approvalTimeout}s
                </span>
              </div>
            </div>
            <div className="setting-row">
              <div className="setting-info">
                <label className="setting-label">Session Provider</label>
                <span className="setting-description">Default AI provider for new sessions</span>
              </div>
              <select
                className="setting-select"
                value={sessionProvider}
                onChange={(e) => updateSettings({ session_provider: e.target.value })}
              >
                {providers.map((p) => (
                  <option key={p.key} value={p.key} disabled={!p.available}>
                    {p.label}{!p.available ? ' (not installed)' : ''}
                  </option>
                ))}
              </select>
            </div>
          </div>
        </div>

        {/* Appearance */}
        <div className="settings-section">
          <h3>Appearance</h3>
          <div className="settings-group">
            <div className="setting-row">
              <div className="setting-info">
                <label className="setting-label">Theme</label>
                <span className="setting-description">Choose the application color scheme</span>
              </div>
              <select
                className="setting-select"
                value={theme}
                onChange={(e) => updateSettings({ theme: e.target.value })}
              >
                <option value="dark">Dark</option>
                <option value="light">Light</option>
                <option value="system">System</option>
              </select>
            </div>
          </div>
        </div>
      </div>
      <HostsSettingsSection />
    </div>
  );
};
