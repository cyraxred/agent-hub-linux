import React, { useState } from 'react';
import { useHostsStore, type ConnectionStatus } from '@/store/hosts';
import type { HostConfig } from '@/types/hosts';
import { LOCALHOST_HOST_ID, defaultHostConfig } from '@/types/hosts';
import { vaultSet, vaultHas } from '@/lib/vault';

function genId(): string {
  return crypto.randomUUID();
}

function statusColor(status: ConnectionStatus): string {
  switch (status) {
    case 'connected': return 'var(--accent-green, #3fb950)';
    case 'connecting': return 'var(--accent-yellow, #d29922)';
    case 'error': return 'var(--accent-red, #ff7b72)';
    default: return 'var(--text-tertiary)';
  }
}

interface HostFormState {
  label: string;
  kind: 'direct' | 'ssh';
  baseUrl: string;
  sshHost: string;
  sshPort: string;
  sshUser: string;
  remotePort: string;
  sshAuthMethod: 'password' | 'key' | 'none';
  credential: string; // password or PEM key content — never persisted
}

function emptyForm(): HostFormState {
  return {
    label: '',
    kind: 'direct',
    baseUrl: 'http://192.168.1.10:18080',
    sshHost: '',
    sshPort: '22',
    sshUser: '',
    remotePort: '18080',
    sshAuthMethod: 'none',
    credential: '',
  };
}

export const HostsSettingsSection: React.FC = () => {
  const { hosts, runtimeState, addHost, removeHost, connectHost, disconnectHost } =
    useHostsStore();

  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState<HostFormState>(emptyForm());
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [connectingId, setConnectingId] = useState<string | null>(null);

  const updateForm = (changes: Partial<HostFormState>) =>
    setForm((prev) => ({ ...prev, ...changes }));

  const handleSave = async () => {
    if (!form.label.trim()) { setFormError('Label is required'); return; }
    if (form.kind === 'direct' && !form.baseUrl.trim()) {
      setFormError('URL is required'); return;
    }
    if (form.kind === 'ssh' && !form.sshHost.trim()) {
      setFormError('SSH host is required'); return;
    }

    setSaving(true);
    setFormError(null);
    try {
      const id = genId();
      let vaultKeyRef: string | null = null;

      if (form.kind === 'ssh' && form.credential.trim() && form.sshAuthMethod !== 'none') {
        vaultKeyRef = `host-${id}-cred`;
        await vaultSet(vaultKeyRef, form.credential.trim());
      }

      const config: HostConfig = {
        id,
        label: form.label.trim(),
        kind: form.kind,
        baseUrl: form.baseUrl.trim(),
        sshHost: form.sshHost.trim(),
        sshPort: parseInt(form.sshPort, 10) || 22,
        sshUser: form.sshUser.trim(),
        remotePort: parseInt(form.remotePort, 10) || 18080,
        vaultKeyRef,
        sshAuthMethod: form.sshAuthMethod === 'none' ? null : form.sshAuthMethod,
      };

      addHost(config);
      setForm(emptyForm());
      setShowForm(false);
    } catch (err) {
      setFormError((err as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const handleConnect = async (id: string) => {
    setConnectingId(id);
    try {
      await connectHost(id);
    } catch {
      // Error shown via runtimeState
    } finally {
      setConnectingId(null);
    }
  };

  return (
    <div className="settings-section">
      <div className="settings-section-header">
        <h3>Remote Hosts</h3>
        <button
          className="btn btn-ghost btn-xs"
          onClick={() => { setShowForm(!showForm); setFormError(null); }}
        >
          {showForm ? 'Cancel' : '+ Add Host'}
        </button>
      </div>

      {/* Add host form */}
      {showForm && (
        <div className="host-form">
          <div className="setting-row">
            <label className="setting-label">Label</label>
            <input
              className="setting-input"
              value={form.label}
              onChange={(e) => updateForm({ label: e.target.value })}
              placeholder="dev-server"
            />
          </div>

          <div className="setting-row">
            <label className="setting-label">Connection</label>
            <div className="radio-group">
              {(['direct', 'ssh'] as const).map((k) => (
                <label key={k} className="radio-label">
                  <input
                    type="radio"
                    value={k}
                    checked={form.kind === k}
                    onChange={() => updateForm({ kind: k })}
                  />
                  {k === 'direct' ? 'Direct (HTTP)' : 'SSH Tunnel'}
                </label>
              ))}
            </div>
          </div>

          {form.kind === 'direct' && (
            <div className="setting-row">
              <label className="setting-label">Backend URL</label>
              <input
                className="setting-input"
                value={form.baseUrl}
                onChange={(e) => updateForm({ baseUrl: e.target.value })}
                placeholder="http://192.168.1.10:18080"
              />
            </div>
          )}

          {form.kind === 'ssh' && (
            <>
              <div className="setting-row">
                <label className="setting-label">SSH Host</label>
                <input
                  className="setting-input"
                  value={form.sshHost}
                  onChange={(e) => updateForm({ sshHost: e.target.value })}
                  placeholder="192.168.1.10"
                />
              </div>
              <div className="setting-row">
                <label className="setting-label">SSH Port</label>
                <input
                  className="setting-input"
                  style={{ width: 80 }}
                  type="number"
                  value={form.sshPort}
                  onChange={(e) => updateForm({ sshPort: e.target.value })}
                />
              </div>
              <div className="setting-row">
                <label className="setting-label">SSH User</label>
                <input
                  className="setting-input"
                  value={form.sshUser}
                  onChange={(e) => updateForm({ sshUser: e.target.value })}
                  placeholder="ubuntu"
                />
              </div>
              <div className="setting-row">
                <label className="setting-label">Remote Port</label>
                <input
                  className="setting-input"
                  style={{ width: 80 }}
                  type="number"
                  value={form.remotePort}
                  onChange={(e) => updateForm({ remotePort: e.target.value })}
                />
              </div>
              <div className="setting-row">
                <label className="setting-label">Auth</label>
                <select
                  className="setting-select"
                  value={form.sshAuthMethod}
                  onChange={(e) =>
                    updateForm({ sshAuthMethod: e.target.value as 'password' | 'key' | 'none' })
                  }
                >
                  <option value="none">None / SSH agent</option>
                  <option value="password">Password</option>
                  <option value="key">Private key (PEM)</option>
                </select>
              </div>
              {form.sshAuthMethod === 'password' && (
                <div className="setting-row">
                  <label className="setting-label">Password</label>
                  <input
                    className="setting-input"
                    type="password"
                    value={form.credential}
                    onChange={(e) => updateForm({ credential: e.target.value })}
                    placeholder="Stored encrypted in vault"
                  />
                </div>
              )}
              {form.sshAuthMethod === 'key' && (
                <div className="setting-row">
                  <label className="setting-label">PEM Key</label>
                  <textarea
                    className="setting-input"
                    rows={4}
                    style={{ fontFamily: 'monospace', fontSize: 11 }}
                    value={form.credential}
                    onChange={(e) => updateForm({ credential: e.target.value })}
                    placeholder="-----BEGIN OPENSSH PRIVATE KEY-----"
                  />
                </div>
              )}
            </>
          )}

          {formError && (
            <span className="text-error" style={{ fontSize: 'var(--font-size-xs)' }}>
              {formError}
            </span>
          )}

          <div style={{ display: 'flex', gap: 'var(--space-sm)', marginTop: 'var(--space-sm)' }}>
            <button
              className="btn btn-primary btn-xs"
              onClick={handleSave}
              disabled={saving}
            >
              {saving ? 'Saving…' : 'Save Host'}
            </button>
            <button
              className="btn btn-ghost btn-xs"
              onClick={() => { setShowForm(false); setForm(emptyForm()); setFormError(null); }}
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Host list */}
      {hosts.length === 0 && !showForm && (
        <p className="settings-empty-hint">No remote hosts configured.</p>
      )}

      {hosts.map((host) => {
        const rt = runtimeState[host.id];
        const status: ConnectionStatus = rt?.status ?? 'disconnected';
        const isConnecting = connectingId === host.id;

        return (
          <div key={host.id} className="host-row">
            <span className="status-dot" style={{ backgroundColor: statusColor(status), flexShrink: 0 }} />
            <div className="host-row-info">
              <span className="host-row-label">{host.label}</span>
              <span className="host-row-meta">
                {host.kind === 'direct' ? host.baseUrl : `${host.sshUser}@${host.sshHost}:${host.sshPort} → :${host.remotePort}`}
                {host.vaultKeyRef && vaultHas(host.vaultKeyRef) && (
                  <span className="provider-badge" style={{ marginLeft: 4 }}>
                    {host.sshAuthMethod === 'key' ? 'key' : 'password'}
                  </span>
                )}
              </span>
              {rt?.error && (
                <span className="text-error" style={{ fontSize: 'var(--font-size-xs)' }}>
                  {rt.error}
                </span>
              )}
            </div>
            <div className="host-row-actions">
              {status === 'connected' ? (
                <button
                  className="btn btn-ghost btn-xs"
                  onClick={() => disconnectHost(host.id)}
                >
                  Disconnect
                </button>
              ) : (
                <button
                  className="btn btn-primary btn-xs"
                  onClick={() => handleConnect(host.id)}
                  disabled={isConnecting || status === 'connecting'}
                >
                  {isConnecting ? 'Connecting…' : 'Connect'}
                </button>
              )}
              <button
                className="btn btn-ghost btn-xs"
                style={{ color: 'var(--accent-red, #ff7b72)' }}
                onClick={() => removeHost(host.id)}
                title="Remove host"
              >
                ✕
              </button>
            </div>
          </div>
        );
      })}
    </div>
  );
};
