import { create } from 'zustand';
import type { AttentionNotification } from '@/types/generated';
import { SessionId } from '@/types/session';

/**
 * An AttentionNotification whose session_id has been scoped to its host via SessionId.
 * Mirrors the TaggedSession pattern in sessions.ts.
 */
export type TaggedNotification = Omit<AttentionNotification, 'session_id'> & {
  session_id: SessionId;
};

/**
 * Minimal repository shape required by syncFromRepositories.
 * Defined locally to avoid a circular import with store/sessions.ts.
 */
type SyncableRepository = {
  worktrees?: Array<{
    sessions?: Array<{
      id: SessionId;
      needs_attention?: string | null;
      last_activity_at: string;
    }>;
  }>;
};

interface NotificationsState {
  notifications: TaggedNotification[];
  /** Session IDs that already have a notification (prevents duplicates). */
  _trackedSessionIds: Set<SessionId>;
  addNotification: (notification: TaggedNotification) => void;
  resolveNotification: (notificationId: string) => void;
  resolveBySessionId: (sessionId: SessionId) => void;
  setNotifications: (notifications: TaggedNotification[]) => void;
  /** Sync notifications from session data (non-monitored sessions with needs_attention). */
  syncFromRepositories: (repositories: SyncableRepository[]) => void;
}

/** Extract all sessions from a repository tree. */
function flattenSessions(repos: SyncableRepository[]): Array<{ id: SessionId; needs_attention?: string | null; last_activity_at: string }> {
  const sessions: Array<{ id: SessionId; needs_attention?: string | null; last_activity_at: string }> = [];
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
      const sid = notification.session_id;
      if (state._trackedSessionIds.has(sid)) return state;
      const tracked = new Set(state._trackedSessionIds);
      tracked.add(sid);
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
