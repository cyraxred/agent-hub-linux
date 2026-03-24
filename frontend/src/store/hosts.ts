/**
 * Hosts store — persisted list of remote host configurations.
 *
 * SSH credentials are stored in the backend CredentialStore (OS keyring).
 * This store only holds non-sensitive config and runtime connection state.
 */

import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { HostConfig } from '@/types/hosts';
import { LOCALHOST_HOST_ID } from '@/types/hosts';
import { api } from '@/api/client';

export type ConnectionStatus =
  | 'disconnected'
  | 'connecting'
  | 'connected'
  | 'auth_required'
  | 'error';

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
  authenticateHost: (id: string, username: string, password: string) => Promise<void>;

  isConnected: (id: string) => boolean;
  connectedHostIds: () => string[];
}

export const useHostsStore = create<HostsState>()(
  persist(
    (set, get) => ({
      hosts: [],
      runtimeState: {},

      addHost: (config) =>
        set((s) => {
          const maxSeq = s.hosts.reduce((m, h) => Math.max(m, h.hostSeq ?? 0), 0);
          return { hosts: [...s.hosts, { ...config, hostSeq: maxSeq + 1 }] };
        }),

      updateHost: (id, changes) =>
        set((s) => ({
          hosts: s.hosts.map((h) => (h.id === id ? { ...h, ...changes } : h)),
        })),

      removeHost: async (id) => {
        // Disconnect first if connected
        if (get().runtimeState[id]?.status === 'connected') {
          await get().disconnectHost(id).catch(() => {});
        }
        // Delete backend credentials
        api.hosts.deleteCredential(id).catch(() => {});
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
          // SSH creds are retrieved by the backend from CredentialStore
          const resp = await api.hosts.connect({
            id: host.id,
            label: host.label,
            kind: host.kind,
            base_url: host.kind === 'direct' ? host.baseUrl : '',
            ssh_host: host.sshHost,
            ssh_port: host.sshPort,
            ssh_user: host.sshUser,
            ssh_password: '',
            ssh_key: '',
            remote_port: host.remotePort,
          });

          if (resp.auth_required) {
            // Remote requires PAM authentication — UI will show prompt
            set((s) => ({
              runtimeState: {
                ...s.runtimeState,
                [id]: { status: 'auth_required', error: null },
              },
            }));
          } else {
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
          }
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

      authenticateHost: async (id, username, password) => {
        try {
          await api.hosts.authenticate(id, username, password);
          set((s) => ({
            runtimeState: {
              ...s.runtimeState,
              [id]: { status: 'connected', error: null },
            },
          }));
          // Refresh repos
          import('@/store/sessions').then(({ useSessionsStore }) => {
            useSessionsStore.getState().fetchAllRepositories().catch(() => {});
          });
        } catch (err) {
          set((s) => ({
            runtimeState: {
              ...s.runtimeState,
              [id]: { status: 'auth_required', error: (err as Error).message },
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
