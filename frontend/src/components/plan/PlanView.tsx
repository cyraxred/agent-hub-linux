import React, { useEffect, useMemo, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import { api } from '@/api/client';
import type { PlanInfo, SessionMonitorState } from '@/types/generated';

interface PlanViewProps {
  sessionId: string;
}

/** Format an ISO timestamp as "HH:MM MM/DD". */
function formatTimestamp(iso: string | undefined): string {
  if (!iso) return '';
  const d = new Date(iso);
  if (isNaN(d.getTime())) return '';
  const hh = String(d.getHours()).padStart(2, '0');
  const mm = String(d.getMinutes()).padStart(2, '0');
  const mo = String(d.getMonth() + 1).padStart(2, '0');
  const dd = String(d.getDate()).padStart(2, '0');
  return `${hh}:${mm} ${mo}/${dd}`;
}

/** Extract the filename from a file path. */
function planLabel(plan: PlanInfo): string {
  const parts = plan.file_path.split('/');
  return parts[parts.length - 1] ?? plan.file_path;
}

/** Build a dropdown label: "filename — HH:MM MM/DD" */
function planOptionLabel(plan: PlanInfo): string {
  const name = planLabel(plan);
  const ts = formatTimestamp(plan.timestamp);
  return ts ? `${name} — ${ts}` : name;
}

export const PlanView: React.FC<PlanViewProps> = ({ sessionId }) => {
  const [state, setState] = useState<SessionMonitorState | null>(null);
  const [loading, setLoading] = useState(true);
  const [selectedIndex, setSelectedIndex] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setState(null);
    setSelectedIndex(0);
    setLoading(true);
    api.sessions.getState(sessionId).then((s) => {
      if (!cancelled) { setState(s); setLoading(false); }
    }).catch(() => {
      if (!cancelled) { setState(null); setLoading(false); }
    });
    return () => { cancelled = true; };
  }, [sessionId]);

  // Plans list, reversed so latest is first
  const plans = useMemo(() => {
    if (state?.plans && state.plans.length > 0) {
      return [...state.plans].reverse();
    }
    return [];
  }, [state?.plans]);

  const selectedPlan = plans.length > 0 ? plans[selectedIndex] : undefined;
  const planContent = selectedPlan?.content ?? state?.plan_content ?? null;

  if (loading) {
    return (
      <div className="plan-view empty-state">
        <p>Loading plan...</p>
      </div>
    );
  }

  if (!planContent) {
    return (
      <div className="plan-view empty-state">
        <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1">
          <path d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4" />
        </svg>
        <h3>No Plan Available</h3>
        <p>This session does not have an execution plan yet. Plans are detected from Write/Edit tool calls to .claude/plans/ paths.</p>
      </div>
    );
  }

  return (
    <div className="plan-view">
      {/* Plan selector dropdown + timestamp bar */}
      {plans.length > 0 && (
        <div style={{
          display: 'flex', alignItems: 'center', gap: 'var(--space-sm)',
          padding: 'var(--space-xs) var(--space-sm)',
          borderBottom: '1px solid var(--border-secondary)',
          fontSize: 'var(--font-size-xs)',
          color: 'var(--text-secondary)',
        }}>
          {plans.length > 1 ? (
            <select
              value={selectedIndex}
              onChange={(e) => setSelectedIndex(Number(e.target.value))}
              style={{
                background: 'var(--bg-tertiary)',
                color: 'var(--text-primary)',
                border: '1px solid var(--border-secondary)',
                borderRadius: 4,
                padding: '2px 6px',
                fontSize: 'var(--font-size-xs)',
              }}
            >
              {plans.map((p, i) => (
                <option key={i} value={i}>{planOptionLabel(p)}</option>
              ))}
            </select>
          ) : (
            <span>{planOptionLabel(plans[0]!)}</span>
          )}
        </div>
      )}

      <div className="plan-markdown">
        <ReactMarkdown
          components={{
            h1: ({ children, ...props }) => (
              <h1 className="plan-h1" {...props}>{children}</h1>
            ),
            h2: ({ children, ...props }) => (
              <h2 className="plan-h2" {...props}>{children}</h2>
            ),
            h3: ({ children, ...props }) => (
              <h3 className="plan-h3" {...props}>{children}</h3>
            ),
            code: ({ className, children, ...props }) => {
              const isBlock = className?.startsWith('language-');
              if (isBlock) {
                return (
                  <pre className={`plan-code-block ${className ?? ''}`}>
                    <code {...props}>{children}</code>
                  </pre>
                );
              }
              return <code className="plan-inline-code" {...props}>{children}</code>;
            },
            a: ({ children, href, ...props }) => (
              <a href={href} target="_blank" rel="noopener noreferrer" className="plan-link" {...props}>
                {children}
              </a>
            ),
            ul: ({ children, ...props }) => (
              <ul className="plan-list" {...props}>{children}</ul>
            ),
            ol: ({ children, ...props }) => (
              <ol className="plan-list ordered" {...props}>{children}</ol>
            ),
            blockquote: ({ children, ...props }) => (
              <blockquote className="plan-blockquote" {...props}>{children}</blockquote>
            ),
            table: ({ children, ...props }) => (
              <div className="plan-table-wrapper">
                <table className="plan-table" {...props}>{children}</table>
              </div>
            ),
          }}
        >
          {planContent}
        </ReactMarkdown>
      </div>
    </div>
  );
};
