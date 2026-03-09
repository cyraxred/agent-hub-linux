import { useEffect, useRef, useState, useCallback } from 'react';
import { wsClient, type SubscriptionInfo } from '@/api/websocket';
import { useSessionsStore } from '@/store/sessions';
import { useStatsStore } from '@/store/stats';
import { useNotificationsStore } from '@/store/notifications';
import { historyAppendBus } from '@/store/sessions';
import type { ServerMessage } from '@/types/generated';

export function useWebSocket() {
  const [connected, setConnected] = useState(wsClient.connected);
  const setSessionState = useSessionsStore((s) => s.setSessionState);
  const setRepositories = useSessionsStore((s) => s.setRepositories);
  const setStats = useStatsStore((s) => s.setStats);
  const addNotification = useNotificationsStore((s) => s.addNotification);
  const resolveNotification = useNotificationsStore((s) => s.resolveNotification);
  const resolveBySessionId = useNotificationsStore((s) => s.resolveBySessionId);
  const setNotifications = useNotificationsStore((s) => s.setNotifications);
  const initialized = useRef(false);

  const handleMessage = useCallback(
    (message: ServerMessage) => {
      switch (message.kind) {
        case 'session_state_update': {
          setSessionState(message.session_id, message.state);
          // Auto-resolve notifications when session leaves attention state
          const statusKind = message.state?.status?.kind;
          if (statusKind && statusKind !== 'awaiting_approval' && statusKind !== 'awaiting_question') {
            resolveBySessionId(message.session_id);
          }
          break;
        }
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
        case 'notification':
          addNotification(message.notification);
          break;
        case 'notification_resolved':
          resolveNotification(message.notification_id);
          break;
        case 'notification_list':
          setNotifications(message.notifications ?? []);
          break;
        case 'error':
          console.error('[WS] Server error:', message.message);
          break;
        default:
          break;
      }
    },
    [setSessionState, setRepositories, setStats, addNotification, resolveNotification, resolveBySessionId, setNotifications],
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
