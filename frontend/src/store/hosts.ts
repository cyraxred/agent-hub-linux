/**
 * Hosts store — persisted list of remote host configurations.
 *
 * Secrets (SSH passwords, PEM keys) are stored in the vault, not here.
 * This store only holds non-sensitive config and runtime connection state.
 */

import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { HostConfig } from '@/types/hosts';
import { LOCALHOST_HOST_ID } from '@/types/hosts';
import { vaultDelete, vaultGet } from '@/lib/vault';
import { api } from '@/api/client';

export type ConnectionStatus = 'disconnected' | 'connecting' | 'connected' | 'error';

export interface HostRuntimeState {
  status: ConnectionStatus;
  error: string | null;
}

interface HostsState {
  /** Configured remote hosts (persisted). */
  hosts: HostConfig[];
  /** Runtime connection state per host ID (not persisted). */
  runtimeState: Record<string, HostRuntimeState>;

  addHost: (config: HostConfig) => void;
  updateHost: (id: string, changes: Partial<HostConfig>) => void;
  removeHost: (id: string) => Promise<void>;

  connectHost: (id: string) => Promise<void>;
  disconnectHost: (id: string) => Promise<void>;

  isConnected: (id: string) => boolean;
  connectedHostIds: () => string[];
}

export const useHostsStore = create<HostsState>()(
  persist(
    (set, get) => ({
      hosts: [],
      runtimeState: {},

      addHost: (config) =>
        set((s) => ({ hosts: [...s.hosts, config] })),

      updateHost: (id, changes) =>
        set((s) => ({
          hosts: s.hosts.map((h) => (h.id === id ? { ...h, ...changes } : h)),
        })),

      removeHost: async (id) => {
        const host = get().hosts.find((h) => h.id === id);
        // Disconnect first if connected
        if (get().runtimeState[id]?.status === 'connected') {
          await get().disconnectHost(id).catch(() => {});
        }
        // Delete vault entry
        if (host?.vaultKeyRef) {
          vaultDelete(host.vaultKeyRef);
        }
        set((s) => {
          const runtimeState = { ...s.runtimeState };
          delete runtimeState[id];
          return {
            hosts: s.hosts.filter((h) => h.id !== id),
            runtimeState,
          };
        });
      },

      connectHost: async (id) => {
        const host = get().hosts.find((h) => h.id === id);
        if (!host) return;

        set((s) => ({
          runtimeState: {
            ...s.runtimeState,
            [id]: { status: 'connecting', error: null },
          },
        }));

        try {
          // Retrieve credential from vault
          let sshPassword = '';
          let sshKey = '';
          if (host.vaultKeyRef) {
            const secret = await vaultGet(host.vaultKeyRef);
            if (secret) {
              if (host.sshAuthMethod === 'password') sshPassword = secret;
              else if (host.sshAuthMethod === 'key') sshKey = secret;
            }
          }

          await api.hosts.connect({
            id: host.id,
            label: host.label,
            kind: host.kind,
            base_url: host.kind === 'direct' ? host.baseUrl : '',
            ssh_host: host.sshHost,
            ssh_port: host.sshPort,
            ssh_user: host.sshUser,
            ssh_password: sshPassword,
            ssh_key: sshKey,
            remote_port: host.remotePort,
          });

          set((s) => ({
            runtimeState: {
              ...s.runtimeState,
              [id]: { status: 'connected', error: null },
            },
          }));

          // Refresh repos so the newly-connected host's sessions appear
          import('@/store/sessions').then(({ useSessionsStore }) => {
            useSessionsStore.getState().fetchAllRepositories().catch(() => {});
          });
        } catch (err) {
          set((s) => ({
            runtimeState: {
              ...s.runtimeState,
              [id]: { status: 'error', error: (err as Error).message },
            },
          }));
          throw err;
        }
      },

      disconnectHost: async (id) => {
        try {
          await api.hosts.disconnect(id);
        } catch {
          // Best-effort
        }
        set((s) => ({
          runtimeState: {
            ...s.runtimeState,
            [id]: { status: 'disconnected', error: null },
          },
        }));
        // Clear stale repos/sessions for this host
        import('@/store/sessions').then(({ useSessionsStore }) => {
          useSessionsStore.getState().setHostRepositories(id, []);
        });
      },

      isConnected: (id) => {
        if (id === LOCALHOST_HOST_ID) return true;
        return get().runtimeState[id]?.status === 'connected';
      },

      connectedHostIds: () =>
        get()
          .hosts.filter((h) => get().runtimeState[h.id]?.status === 'connected')
          .map((h) => h.id),
    }),
    {
      name: 'agent-hub.hosts',
      partialize: (s) => ({ hosts: s.hosts }),
    },
  ),
);
