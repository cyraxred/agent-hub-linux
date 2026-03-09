/** Frontend-only host configuration types. Not generated from Python models. */

export type HostKind = 'direct' | 'ssh';
export type SshAuthMethod = 'password' | 'key';

/** A configured remote host. Stored in Zustand + localStorage (no secrets). */
export interface HostConfig {
  id: string;
  label: string;
  kind: HostKind;
  // direct
  baseUrl: string;        // e.g. "http://192.168.1.10:18080"
  // ssh
  sshHost: string;
  sshPort: number;        // default 22
  sshUser: string;
  remotePort: number;     // default 18080
  /** Key into the vault where the password or PEM key is stored. Null = no credential stored. */
  vaultKeyRef: string | null;
  sshAuthMethod: SshAuthMethod | null;
}

/** The implicit built-in localhost host — never persisted in the host list. */
export const LOCALHOST_HOST_ID = '__local__';

export function defaultHostConfig(): Omit<HostConfig, 'id' | 'label'> {
  return {
    kind: 'direct',
    baseUrl: 'http://192.168.1.10:18080',
    sshHost: '',
    sshPort: 22,
    sshUser: '',
    remotePort: 18080,
    vaultKeyRef: null,
    sshAuthMethod: null,
  };
}
