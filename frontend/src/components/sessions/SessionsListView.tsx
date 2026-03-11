import React from 'react';
import { useSessionsStore, type TaggedSession } from '@/store/sessions';
import { SessionId } from "@/types/session";
import { SessionRow } from './SessionRow';

interface SessionsListViewProps {
  sessions: TaggedSession[];
  header?: string;
}

export const SessionsListView: React.FC<SessionsListViewProps> = ({
  sessions,
  header,
}) => {
  const selectedSessionId = useSessionsStore((s) => s.selectedSessionId);
  const sessionStates = useSessionsStore((s) => s.sessionStates);
  const monitoredSessionIds = useSessionsStore((s) => s.monitoredSessionIds);
  const selectSession = useSessionsStore((s) => s.selectSession);
  const startMonitoring = useSessionsStore((s) => s.startMonitoring);

  if (sessions.length === 0) {
    return (
      <div className="sessions-list-empty">
        <p>No sessions found</p>
      </div>
    );
  }

  return (
    <div className="sessions-list">
      <div className="sessions-list-header">
        <span className="sessions-count">
          {header ?? `${sessions.length} session${sessions.length !== 1 ? 's' : ''}`}
        </span>
      </div>
      <div className="sessions-list-body">
        {sessions.map((session) => (
          <SessionRow
            key={session.id}
            session={session}
            isSelected={selectedSessionId === session.id}
            isMonitored={monitoredSessionIds.has(session.id)}
            monitorState={sessionStates[session.id]}
            onClick={() => selectSession(session.id)}
            onDoubleClick={() =>
              startMonitoring(
                session.id,
                session.project_path,
                session.session_file_path,
              )
            }
          />
        ))}
      </div>
    </div>
  );
};
