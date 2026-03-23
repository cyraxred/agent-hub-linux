import { useEffect, useRef, useState, useCallback } from 'react';
import { wsClient, wsManager, type SubscriptionInfo } from '@/api/websocket';
import { useSessionsStore } from '@/store/sessions';
import { useHostsStore } from '@/store/hosts';
import { useStatsStore } from '@/store/stats';
import { historyAppendBus } from '@/store/sessions';
import { LOCALHOST_HOST_ID } from '@/types/hosts';
import { SessionId } from '@/types/session';
import type { ServerMessage } from '@/types/generated';

/** Resolve the numeric host seq for a string host ID (0 = localhost). */
function hostSeqFor(hostId: string): number {
  if (hostId === LOCALHOST_HOST_ID) return 0;
  return useHostsStore.getState().hosts.find((h) => h.id === hostId)?.hostSeq ?? 0;
}

export function useWebSocket() {
  const [connected, setConnected] = useState(wsClient.connected);
  const setSessionState = useSessionsStore((s) => s.setSessionState);
  const setHostRepositories = useSessionsStore((s) => s.setHostRepositories);
  const setStats = useStatsStore((s) => s.setStats);
  const connectedHostIds = useHostsStore((s) => s.connectedHostIds);
  const initialized = useRef(false);

  const handleMessage = useCallback(
    (message: ServerMessage, hostId: string) => {
      const seq = hostSeqFor(hostId);
      switch (message.kind) {
        case 'sessions_updated':
          setHostRepositories(hostId, message.repositories ?? []);
          break;
        case 'stats_updated':
          setStats(message.provider, message.stats);
          break;
        case 'session_history_append':
          historyAppendBus.notify(
            SessionId.wrap(message.session_id, seq),
            message.entries,
            message.total_lines,
          );
          break;
        case 'session_update': {
          const sid = SessionId.wrap(message.session_id, seq);
          useSessionsStore.getState().setSessionUpdate(sid, message);
          // Also update monitor state if present
          if (message.monitor_state) {
            setSessionState(sid, message.monitor_state);
          }
          break;
        }
        case 'terminal_output':
          break;
        case 'search_results':
          break;
        case 'error':
          console.error('[WS] Server error:', message.message);
          break;
        default:
          break;
      }
    },
    [
      setSessionState,
      setHostRepositories,
      setStats,
    ],
  );

  useEffect(() => {
    // Local backend WS
    const unsubMessage = wsClient.onMessage((msg) => handleMessage(msg, LOCALHOST_HOST_ID));
    const unsubConnection = wsClient.onConnection(setConnected);

    if (!initialized.current) {
      initialized.current = true;
      wsClient.connect();
    } else {
      setConnected(wsClient.connected);
    }

    return () => {
      unsubMessage();
      unsubConnection();
    };
  }, [handleMessage]);

  // Connect/disconnect remote host WebSockets when host connection state changes
  useEffect(() => {
    const ids = connectedHostIds();
    for (const hostId of ids) {
      const client = wsManager.getOrCreate(hostId);
      if (!client.connected) {
        client.onMessage((msg) => handleMessage(msg, hostId));
        client.connect();
      }
    }
    // Disconnect any that are no longer in the connected list
    // (handled by disconnectHost in store)
  }, [connectedHostIds, handleMessage]);

  const subscribe = useCallback((info: SubscriptionInfo) => {
    wsClient.subscribe(info);
  }, []);

  const unsubscribe = useCallback((sessionId: SessionId) => {
    wsClient.unsubscribe(sessionId);
  }, []);

  const sendTerminalInput = useCallback((sessionKey: string, data: string) => {
    wsClient.sendTerminalInput(sessionKey, data);
  }, []);

  const sendTerminalResize = useCallback((sessionKey: string, cols: number, rows: number) => {
    wsClient.sendTerminalResize(sessionKey, cols, rows);
  }, []);

  const refreshSessions = useCallback(() => {
    wsClient.refreshSessions();
  }, []);

  return {
    connected,
    subscribe,
    unsubscribe,
    sendTerminalInput,
    sendTerminalResize,
    refreshSessions,
  };
}
