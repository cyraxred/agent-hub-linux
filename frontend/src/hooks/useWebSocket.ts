import { useEffect, useRef, useState, useCallback } from 'react';
import { wsClient, wsManager, type SubscriptionInfo } from '@/api/websocket';
import { useSessionsStore } from '@/store/sessions';
import { useHostsStore } from '@/store/hosts';
import { useStatsStore } from '@/store/stats';
import { useNotificationsStore } from '@/store/notifications';
import { historyAppendBus } from '@/store/sessions';
import { LOCALHOST_HOST_ID } from '@/types/hosts';
import type { ServerMessage } from '@/types/generated';

export function useWebSocket() {
  const [connected, setConnected] = useState(wsClient.connected);
  const setSessionState = useSessionsStore((s) => s.setSessionState);
  const setHostRepositories = useSessionsStore((s) => s.setHostRepositories);
  const setStats = useStatsStore((s) => s.setStats);
  const addNotification = useNotificationsStore((s) => s.addNotification);
  const resolveNotification = useNotificationsStore((s) => s.resolveNotification);
  const resolveBySessionId = useNotificationsStore((s) => s.resolveBySessionId);
  const setNotifications = useNotificationsStore((s) => s.setNotifications);
  const connectedHostIds = useHostsStore((s) => s.connectedHostIds);
  const initialized = useRef(false);

  const handleMessage = useCallback(
    (message: ServerMessage, hostId: string) => {
      switch (message.kind) {
        case 'session_state_update': {
          setSessionState(message.session_id, message.state);
          const statusKind = message.state?.status?.kind;
          if (
            statusKind &&
            statusKind !== 'awaiting_approval' &&
            statusKind !== 'awaiting_question'
          ) {
            resolveBySessionId(message.session_id);
          }
          break;
        }
        case 'sessions_updated':
          setHostRepositories(hostId, message.repositories ?? []);
          break;
        case 'stats_updated':
          setStats(message.provider, message.stats);
          break;
        case 'session_history_append':
          historyAppendBus.notify(message.session_id, message.entries, message.total_lines);
          break;
        case 'terminal_output':
          break;
        case 'search_results':
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
    [
      setSessionState,
      setHostRepositories,
      setStats,
      addNotification,
      resolveNotification,
      resolveBySessionId,
      setNotifications,
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

  const unsubscribe = useCallback((sessionId: string) => {
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
