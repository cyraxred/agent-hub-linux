import { useEffect, useRef, useState, useCallback } from 'react';
import { wsClient, type SubscriptionInfo } from '@/api/websocket';
import { useSessionsStore } from '@/store/sessions';
import { useStatsStore } from '@/store/stats';
import { historyAppendBus } from '@/store/sessions';
import type { ServerMessage } from '@/types/generated';

export function useWebSocket() {
  const [connected, setConnected] = useState(wsClient.connected);
  const setSessionState = useSessionsStore((s) => s.setSessionState);
  const setRepositories = useSessionsStore((s) => s.setRepositories);
  const setStats = useStatsStore((s) => s.setStats);
  const initialized = useRef(false);

  const handleMessage = useCallback(
    (message: ServerMessage) => {
      switch (message.kind) {
        case 'session_state_update':
          setSessionState(message.session_id, message.state);
          break;
        case 'sessions_updated':
          setRepositories(message.repositories ?? []);
          break;
        case 'stats_updated':
          setStats(message.provider, message.stats);
          break;
        case 'session_history_append':
          historyAppendBus.notify(
            message.session_id,
            message.entries,
            message.total_lines,
          );
          break;
        case 'terminal_output':
          // Handled directly by terminal components via their own handler
          break;
        case 'search_results':
          // Handled by search store if needed
          break;
        case 'error':
          console.error('[WS] Server error:', message.message);
          break;
        default:
          break;
      }
    },
    [setSessionState, setRepositories, setStats],
  );

  useEffect(() => {
    const unsubMessage = wsClient.onMessage(handleMessage);
    const unsubConnection = wsClient.onConnection(setConnected);

    if (!initialized.current) {
      initialized.current = true;
      wsClient.connect();
    } else {
      // HMR re-mount: sync state from the existing connection
      setConnected(wsClient.connected);
    }

    return () => {
      unsubMessage();
      unsubConnection();
    };
  }, [handleMessage]);

  const subscribe = useCallback((info: SubscriptionInfo) => {
    wsClient.subscribe(info);
  }, []);

  const unsubscribe = useCallback((sessionId: string) => {
    wsClient.unsubscribe(sessionId);
  }, []);

  const sendTerminalInput = useCallback((sessionKey: string, data: string) => {
    wsClient.sendTerminalInput(sessionKey, data);
  }, []);

  const sendTerminalResize = useCallback(
    (sessionKey: string, cols: number, rows: number) => {
      wsClient.sendTerminalResize(sessionKey, cols, rows);
    },
    [],
  );

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
