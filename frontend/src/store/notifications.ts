import { create } from 'zustand';
import type { AttentionNotification, CLISession, SelectedRepository } from '@/types/generated';

interface NotificationsState {
  notifications: AttentionNotification[];
  /** Session IDs that already have a notification (prevents duplicates). */
  _trackedSessionIds: Set<string>;
  addNotification: (notification: AttentionNotification) => void;
  resolveNotification: (notificationId: string) => void;
  resolveBySessionId: (sessionId: string) => void;
  setNotifications: (notifications: AttentionNotification[]) => void;
  /** Sync notifications from session data (non-monitored sessions with needs_attention). */
  syncFromRepositories: (repositories: SelectedRepository[]) => void;
}

/** Extract all sessions from a repository tree. */
function flattenSessions(repos: SelectedRepository[]): CLISession[] {
  const sessions: CLISession[] = [];
  for (const repo of repos) {
    for (const wt of repo.worktrees ?? []) {
      for (const s of wt.sessions ?? []) {
        sessions.push(s);
      }
    }
  }
  return sessions;
}

export const useNotificationsStore = create<NotificationsState>((set, get) => ({
  notifications: [],
  _trackedSessionIds: new Set(),

  addNotification: (notification) =>
    set((state) => {
      if (state._trackedSessionIds.has(notification.session_id)) return state;
      const tracked = new Set(state._trackedSessionIds);
      tracked.add(notification.session_id);
      return {
        notifications: [notification, ...state.notifications],
        _trackedSessionIds: tracked,
      };
    }),

  resolveNotification: (notificationId) =>
    set((state) => {
      const notif = state.notifications.find((n) => n.id === notificationId);
      const tracked = new Set(state._trackedSessionIds);
      if (notif) tracked.delete(notif.session_id);
      return {
        notifications: state.notifications.filter((n) => n.id !== notificationId),
        _trackedSessionIds: tracked,
      };
    }),

  resolveBySessionId: (sessionId) =>
    set((state) => {
      const tracked = new Set(state._trackedSessionIds);
      tracked.delete(sessionId);
      return {
        notifications: state.notifications.filter((n) => n.session_id !== sessionId),
        _trackedSessionIds: tracked,
      };
    }),

  setNotifications: (notifications) => {
    const tracked = new Set(notifications.map((n) => n.session_id));
    set({ notifications, _trackedSessionIds: tracked });
  },

  syncFromRepositories: (repositories) => {
    const sessions = flattenSessions(repositories);
    const current = get();
    const newNotifications = [...current.notifications];
    const tracked = new Set(current._trackedSessionIds);
    let changed = false;

    for (const session of sessions) {
      if (!session.needs_attention) continue;
      if (tracked.has(session.id)) continue;

      const attentionKind = session.needs_attention === 'question'
        ? 'awaiting_question' as const
        : 'awaiting_approval' as const;

      newNotifications.unshift({
        id: `session-${session.id}`,
        session_id: session.id,
        attention_kind: attentionKind,
        tool_name: '',
        timestamp: session.last_activity_at,
        resolved: false,
      });
      tracked.add(session.id);
      changed = true;
    }

    if (changed) {
      set({ notifications: newNotifications, _trackedSessionIds: tracked });
    }
  },
}));
