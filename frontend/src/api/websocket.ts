/**
 * WebSocket client for real-time AgentHub communication.
 *
 * Uses the backend's discriminated-union protocol with `kind` field.
 */

import type { ClientMessage, ServerMessage } from '@/types/generated';
import { SessionId } from '@/types/session';

type MessageHandler = (message: ServerMessage) => void;
type ConnectionHandler = (connected: boolean) => void;

const INITIAL_RECONNECT_DELAY = 1000;
const MAX_RECONNECT_DELAY = 30000;
const RECONNECT_MULTIPLIER = 1.5;

/**
 * Subscription info needed by the backend to start watching a session.
 */
export interface SubscriptionInfo {
  sessionId: SessionId;
  projectPath: string;
  sessionFilePath: string;
}

export class WebSocketClient {
  private ws: WebSocket | null = null;
  private url: string;
  private reconnectDelay = INITIAL_RECONNECT_DELAY;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private messageHandlers = new Set<MessageHandler>();
  private connectionHandlers = new Set<ConnectionHandler>();
  /** Tracked subscriptions so we can re-subscribe on reconnect. */
  private subscriptions = new Map<string, SubscriptionInfo>();
  private intentionallyClosed = false;
  private _connected = false;

  constructor(url?: string) {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    this.url = url ?? `${protocol}//${window.location.host}/ws`;
  }

  get connected(): boolean {
    return this._connected;
  }

  connect(): void {
    if (
      this.ws?.readyState === WebSocket.OPEN ||
      this.ws?.readyState === WebSocket.CONNECTING
    ) {
      return;
    }

    this.intentionallyClosed = false;

    try {
      this.ws = new WebSocket(this.url);
    } catch (err) {
      console.error('[WS] Failed to create WebSocket:', err);
      this.scheduleReconnect();
      return;
    }

    this.ws.onopen = () => {
      console.log('[WS] Connected');
      this._connected = true;
      this.reconnectDelay = INITIAL_RECONNECT_DELAY;
      this.notifyConnectionHandlers(true);

      // Re-subscribe to previously subscribed sessions
      for (const info of this.subscriptions.values()) {
        this.sendRaw({
          kind: 'subscribe_session',
          session_id: SessionId.rawId(info.sessionId),
          project_path: info.projectPath,
          session_file_path: info.sessionFilePath,
        });
      }
    };

    this.ws.onmessage = (event: MessageEvent) => {
      try {
        const message = JSON.parse(event.data as string) as ServerMessage;
        this.notifyMessageHandlers(message);
      } catch (err) {
        console.error('[WS] Failed to parse message:', err);
      }
    };

    this.ws.onclose = (event: CloseEvent) => {
      console.log(`[WS] Disconnected: code=${event.code} reason=${event.reason}`);
      this._connected = false;
      this.notifyConnectionHandlers(false);

      if (!this.intentionallyClosed) {
        this.scheduleReconnect();
      }
    };

    this.ws.onerror = (event: Event) => {
      console.error('[WS] Error:', event);
    };
  }

  disconnect(): void {
    this.intentionallyClosed = true;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.ws) {
      this.ws.close(1000, 'Client disconnect');
      this.ws = null;
    }
    this._connected = false;
    this.notifyConnectionHandlers(false);
  }

  /** Send a typed ClientMessage. */
  send(message: ClientMessage): void {
    this.sendRaw(message);
  }

  /** Subscribe to real-time updates for a session. */
  subscribe(info: SubscriptionInfo): void {
    this.subscriptions.set(info.sessionId, info);
    this.sendRaw({
      kind: 'subscribe_session',
      session_id: SessionId.rawId(info.sessionId),
      project_path: info.projectPath,
      session_file_path: info.sessionFilePath,
    });
  }

  /** Unsubscribe from a session. */
  unsubscribe(sessionId: SessionId): void {
    this.subscriptions.delete(sessionId);
    this.sendRaw({
      kind: 'unsubscribe_session',
      session_id: SessionId.rawId(sessionId),
    });
  }

  /** Send terminal keystrokes. */
  sendTerminalInput(sessionKey: string, data: string): void {
    this.sendRaw({
      kind: 'terminal_input',
      session_key: sessionKey,
      data,
    });
  }

  /** Resize an embedded terminal. */
  sendTerminalResize(sessionKey: string, cols: number, rows: number): void {
    this.sendRaw({
      kind: 'terminal_resize',
      session_key: sessionKey,
      cols,
      rows,
    });
  }

  /** Request a full session list refresh. */
  refreshSessions(): void {
    this.sendRaw({ kind: 'refresh_sessions' });
  }

  /** Register a handler for incoming server messages. Returns unsubscribe fn. */
  onMessage(handler: MessageHandler): () => void {
    this.messageHandlers.add(handler);
    return () => {
      this.messageHandlers.delete(handler);
    };
  }

  /** Register a handler for connection state changes. Returns unsubscribe fn. */
  onConnection(handler: ConnectionHandler): () => void {
    this.connectionHandlers.add(handler);
    return () => {
      this.connectionHandlers.delete(handler);
    };
  }

  // ---- internals ----

  private sendRaw(data: Record<string, unknown> | ClientMessage): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(data));
    } else {
      console.warn('[WS] Cannot send — not connected');
    }
  }

  private notifyMessageHandlers(message: ServerMessage): void {
    for (const handler of this.messageHandlers) {
      try {
        handler(message);
      } catch (err) {
        console.error('[WS] Handler error:', err);
      }
    }
  }

  private notifyConnectionHandlers(connected: boolean): void {
    for (const handler of this.connectionHandlers) {
      try {
        handler(connected);
      } catch (err) {
        console.error('[WS] Connection handler error:', err);
      }
    }
  }

  private scheduleReconnect(): void {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
    }
    console.log(`[WS] Reconnecting in ${this.reconnectDelay}ms...`);
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.connect();
    }, this.reconnectDelay);
    this.reconnectDelay = Math.min(
      this.reconnectDelay * RECONNECT_MULTIPLIER,
      MAX_RECONNECT_DELAY,
    );
  }
}

// ---------------------------------------------------------------------------
// Multi-host WebSocket manager
// ---------------------------------------------------------------------------

/**
 * Manages one ``WebSocketClient`` per connected host.
 *
 * Message handlers registered via ``onMessage`` receive messages from **all**
 * hosts; each handler is called with an additional ``hostId`` argument so the
 * consumer can tag data appropriately.
 */
export class WebSocketManager {
  private clients = new Map<string, WebSocketClient>();

  private _urlForHost(hostId: string): string {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.host;
    if (hostId === '__local__') return `${protocol}//${host}/ws`;
    return `${protocol}//${host}/api/hosts/${encodeURIComponent(hostId)}/proxy/ws`;
  }

  /** Return or create (but do not connect) a client for *hostId*. */
  getOrCreate(hostId: string): WebSocketClient {
    if (!this.clients.has(hostId)) {
      this.clients.set(hostId, new WebSocketClient(this._urlForHost(hostId)));
    }
    return this.clients.get(hostId)!;
  }

  /** Connect a remote host's WebSocket (call after ``api.hosts.connect`` succeeds). */
  connectHost(hostId: string): void {
    this.getOrCreate(hostId).connect();
  }

  /** Disconnect and remove a host's WebSocket. */
  disconnectHost(hostId: string): void {
    const client = this.clients.get(hostId);
    if (client) {
      client.disconnect();
      this.clients.delete(hostId);
    }
  }

  /** Register a message handler across ALL hosts. Returns an unsubscribe fn. */
  onMessage(handler: (message: ServerMessage, hostId: string) => void): () => void {
    const unsubs: Array<() => void> = [];
    for (const [hostId, client] of this.clients) {
      unsubs.push(client.onMessage((msg) => handler(msg, hostId)));
    }
    // Also register on clients added in future (stored for new connectHost calls)
    this._pendingHandlers.add(handler);
    return () => {
      this._pendingHandlers.delete(handler);
      for (const u of unsubs) u();
    };
  }

  private _pendingHandlers = new Set<(message: ServerMessage, hostId: string) => void>();

  /** Internal: wrap a new client so pending handlers receive its messages too. */
  private _wrapClient(hostId: string, client: WebSocketClient): void {
    for (const handler of this._pendingHandlers) {
      client.onMessage((msg) => handler(msg, hostId));
    }
  }

  get(hostId: string): WebSocketClient | undefined {
    return this.clients.get(hostId);
  }
}

export const wsManager = new WebSocketManager();

/** Singleton instance for the local backend — backward-compatible. */
export const wsClient = wsManager.getOrCreate('__local__');
