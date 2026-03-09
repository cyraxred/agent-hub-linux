/**
 * Vault: AES-GCM encrypted secret storage via Web Crypto API.
 *
 * Uses a per-install random salt (stored in localStorage) as PBKDF2 key
 * material.  This provides obfuscation from casual localStorage inspection.
 * The encryption key is derived once and cached for the session.
 */

const VAULT_STORAGE_KEY = 'agent-hub.vault';
const SALT_STORAGE_KEY = 'agent-hub.vault-salt';

type VaultEntry = { iv: string; ciphertext: string };
type VaultData = Record<string, VaultEntry>;

let _cryptoKey: CryptoKey | null = null;

function _b64encode(buf: ArrayBuffer): string {
  return btoa(String.fromCharCode(...new Uint8Array(buf)));
}

function _b64decode(str: string): Uint8Array {
  return Uint8Array.from(atob(str), (c) => c.charCodeAt(0));
}

async function _getOrCreateSalt(): Promise<Uint8Array> {
  const stored = localStorage.getItem(SALT_STORAGE_KEY);
  if (stored) {
    return _b64decode(stored);
  }
  const salt = crypto.getRandomValues(new Uint8Array(16));
  localStorage.setItem(SALT_STORAGE_KEY, _b64encode(salt.buffer));
  return salt;
}

async function _getCryptoKey(): Promise<CryptoKey> {
  if (_cryptoKey) return _cryptoKey;

  const salt = await _getOrCreateSalt();
  const keyMaterial = await crypto.subtle.importKey('raw', salt as Uint8Array<ArrayBuffer>, 'PBKDF2', false, [
    'deriveKey',
  ]);
  _cryptoKey = await crypto.subtle.deriveKey(
    { name: 'PBKDF2', salt: salt as Uint8Array<ArrayBuffer>, iterations: 100_000, hash: 'SHA-256' },
    keyMaterial,
    { name: 'AES-GCM', length: 256 },
    false,
    ['encrypt', 'decrypt'],
  );
  return _cryptoKey;
}

function _loadVault(): VaultData {
  try {
    return JSON.parse(localStorage.getItem(VAULT_STORAGE_KEY) ?? '{}') as VaultData;
  } catch {
    return {};
  }
}

function _saveVault(data: VaultData): void {
  localStorage.setItem(VAULT_STORAGE_KEY, JSON.stringify(data));
}

/** Store an encrypted secret under *key*. */
export async function vaultSet(key: string, secret: string): Promise<void> {
  const cryptoKey = await _getCryptoKey();
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const encoded = new TextEncoder().encode(secret);
  const ciphertext = await crypto.subtle.encrypt({ name: 'AES-GCM', iv }, cryptoKey, encoded);

  const vault = _loadVault();
  vault[key] = { iv: _b64encode(iv.buffer), ciphertext: _b64encode(ciphertext) };
  _saveVault(vault);
}

/** Retrieve and decrypt the secret stored under *key*. Returns null if not found. */
export async function vaultGet(key: string): Promise<string | null> {
  const vault = _loadVault();
  const entry = vault[key];
  if (!entry) return null;

  const cryptoKey = await _getCryptoKey();
  const iv = _b64decode(entry.iv);
  const ciphertext = _b64decode(entry.ciphertext);

  try {
    const decrypted = await crypto.subtle.decrypt({ name: 'AES-GCM', iv: iv as Uint8Array<ArrayBuffer> }, cryptoKey, ciphertext as Uint8Array<ArrayBuffer>);
    return new TextDecoder().decode(decrypted);
  } catch {
    return null;
  }
}

/** Remove the secret stored under *key*. */
export function vaultDelete(key: string): void {
  const vault = _loadVault();
  delete vault[key];
  _saveVault(vault);
}

/** Check whether a vault entry exists for *key*. */
export function vaultHas(key: string): boolean {
  return key in _loadVault();
}
