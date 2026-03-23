/**
 * Browser notification manager for session attention events.
 *
 * Shows a Notification when a session enters an attention state and
 * dismisses it automatically when the attention resolves.
 */

/** Map of sessionId → active browser Notification */
const activeNotifications = new Map<string, Notification>();

/** Request notification permission (call once on app init). */
export function requestNotificationPermission(): void {
  if ('Notification' in window && Notification.permission === 'default') {
    Notification.requestPermission();
  }
}

/** Returns true if browser notifications are available and permitted. */
function canNotify(): boolean {
  return 'Notification' in window && Notification.permission === 'granted';
}

/**
 * Show a browser notification for a session needing attention.
 * If one already exists for this session it is replaced.
 */
export function showAttentionNotification(
  sessionId: string,
  effectiveStatus: string,
  toolName?: string,
): void {
  if (!canNotify()) return;

  // Close any existing notification for this session before creating a new one
  dismissAttentionNotification(sessionId);

  const isQuestion = effectiveStatus === 'awaiting_question';
  const title = isQuestion ? 'Input Needed' : 'Approval Needed';
  const body = isQuestion
    ? `Session ${sessionId.slice(0, 8)} is waiting for your answer`
    : `Session ${sessionId.slice(0, 8)} needs approval${toolName ? ` for ${toolName}` : ''}`;

  const notification = new Notification(title, {
    body,
    tag: `agenthub-${sessionId}`,
    icon: '/favicon.ico',
  });

  notification.onclick = () => {
    window.focus();
    notification.close();
    activeNotifications.delete(sessionId);
  };

  notification.onclose = () => {
    activeNotifications.delete(sessionId);
  };

  activeNotifications.set(sessionId, notification);
}

/** Dismiss the browser notification for a session (if any). */
export function dismissAttentionNotification(sessionId: string): void {
  const existing = activeNotifications.get(sessionId);
  if (existing) {
    existing.close();
    activeNotifications.delete(sessionId);
  }
}
