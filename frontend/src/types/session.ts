/**
 * Branded session ID type.
 *
 * At runtime this is a plain string, so it can be used as a Map/object key
 * and compared with ===.  The brand only exists at the TypeScript level to
 * prevent accidentally passing a raw UUID where a scoped ID is expected.
 *
 * Format:
 *   - localhost (hostId = 0) → the raw UUID unchanged, e.g. "550e8400-…"
 *   - remote host N          → "${N}~${rawUUID}",  e.g. "1~550e8400-…"
 *
 * Using `~` as separator is safe because UUIDs only contain [0-9a-f-].
 */
declare const __sessionBrand: unique symbol;
export type SessionId = string & { readonly [__sessionBrand]: void };

export namespace SessionId {
  /**
   * Wrap a raw session ID from a given host into a typed SessionId.
   * Pass hostId = 0 for localhost (no prefix is added).
   */
  export function wrap(rawSessionId: string, hostId: number): SessionId {
    return (hostId === 0 ? rawSessionId : `${hostId}~${rawSessionId}`) as SessionId;
  }

  /** Convenience alias for localhost sessions (hostId = 0). */
  export function local(rawSessionId: string): SessionId {
    return rawSessionId as SessionId;
  }

  /** Extract the raw session ID without any host prefix. */
  export function rawId(id: SessionId): string {
    const tilde = id.indexOf('~');
    return tilde === -1 ? id : id.slice(tilde + 1);
  }

  /** Extract the numeric host ID (0 = localhost). */
  export function hostId(id: SessionId): number {
    const tilde = id.indexOf('~');
    return tilde === -1 ? 0 : parseInt(id.slice(0, tilde), 10);
  }
}
