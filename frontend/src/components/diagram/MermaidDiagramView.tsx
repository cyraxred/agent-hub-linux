import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import mermaid from 'mermaid';
import { api } from '@/api/client';
import type { MermaidDiagramInfo, SessionMonitorState } from '@/types/generated';

interface MermaidDiagramViewProps {
  sessionId: string;
}

const DIAGRAM_TYPES = [
  { label: 'Flowchart', keyword: 'graph' },
  { label: 'Sequence', keyword: 'sequenceDiagram' },
  { label: 'Class', keyword: 'classDiagram' },
  { label: 'State', keyword: 'stateDiagram' },
  { label: 'ER', keyword: 'erDiagram' },
  { label: 'Gantt', keyword: 'gantt' },
  { label: 'Pie', keyword: 'pie' },
];

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

/** Extract a short label from a diagram's file_path. */
function diagramLabel(d: MermaidDiagramInfo): string {
  if (!d.file_path) return 'Diagram';
  const parts = d.file_path.split('/');
  return parts[parts.length - 1] ?? d.file_path;
}

/** Build a dropdown label: "filename — HH:MM MM/DD" or "Diagram N — HH:MM MM/DD". */
function diagramOptionLabel(d: MermaidDiagramInfo, index: number): string {
  const name = d.file_path ? diagramLabel(d) : `Diagram ${index + 1}`;
  const ts = formatTimestamp(d.timestamp);
  return ts ? `${name} — ${ts}` : name;
}

export const MermaidDiagramView: React.FC<MermaidDiagramViewProps> = ({ sessionId }) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const renderIdRef = useRef(0);

  const [state, setState] = useState<SessionMonitorState | null>(null);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [diagramCode, setDiagramCode] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showEditor, setShowEditor] = useState(false);

  // Reset all state and fetch on session change
  useEffect(() => {
    let cancelled = false;
    setState(null);
    setSelectedIndex(0);
    setDiagramCode(null);
    setError(null);
    if (containerRef.current) containerRef.current.innerHTML = '';

    api.sessions.getState(sessionId).then((s) => {
      if (!cancelled) setState(s);
    }).catch(() => {
      if (!cancelled) setState(null);
    });
    return () => { cancelled = true; };
  }, [sessionId]);

  // Diagrams list, reversed so latest is first
  const diagrams = useMemo(() => {
    if (state?.mermaid_diagrams && state.mermaid_diagrams.length > 0) {
      return [...state.mermaid_diagrams].reverse();
    }
    return [];
  }, [state?.mermaid_diagrams]);

  const selectedDiagram = diagrams.length > 0 ? diagrams[selectedIndex] : undefined;

  // Update diagram code when selected diagram changes
  useEffect(() => {
    setDiagramCode(selectedDiagram?.source ?? null);
  }, [selectedDiagram?.source]);

  const renderDiagram = useCallback(async (code: string) => {
    if (!containerRef.current) return;

    const renderId = ++renderIdRef.current;
    setError(null);

    try {
      mermaid.initialize({
        startOnLoad: false,
        theme: 'dark',
        themeVariables: {
          primaryColor: '#1f6feb',
          primaryTextColor: '#c9d1d9',
          primaryBorderColor: '#30363d',
          lineColor: '#8b949e',
          secondaryColor: '#161b22',
          tertiaryColor: '#0d1117',
          background: '#0d1117',
          mainBkg: '#161b22',
          nodeBorder: '#30363d',
          clusterBkg: '#161b22',
          clusterBorder: '#30363d',
          titleColor: '#c9d1d9',
          edgeLabelBackground: '#161b22',
        },
        flowchart: { curve: 'basis', padding: 15 },
        securityLevel: 'loose',
      });

      const id = `mermaid-${renderId}`;
      const { svg } = await mermaid.render(id, code.trim());

      if (renderId === renderIdRef.current && containerRef.current) {
        containerRef.current.innerHTML = svg;
      }
    } catch (err) {
      if (renderId === renderIdRef.current) {
        setError((err as Error).message);
      }
    }
  }, []);

  useEffect(() => {
    if (diagramCode) {
      renderDiagram(diagramCode);
    }
  }, [diagramCode, renderDiagram]);

  // No mermaid content — show placeholder
  if (!diagramCode && !showEditor) {
    return (
      <div className="mermaid-diagram-view">
        <div className="detail-empty">
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1">
            <rect x="3" y="3" width="18" height="18" rx="2" />
            <path d="M12 8v4M8 14h8" />
            <circle cx="8" cy="8" r="1" fill="currentColor" />
            <circle cx="16" cy="8" r="1" fill="currentColor" />
            <circle cx="12" cy="16" r="1" fill="currentColor" />
          </svg>
          <h3>No Diagrams Yet</h3>
          <p>
            Mermaid diagrams will appear here automatically when the session
            outputs <code>```mermaid</code> code blocks during tool use.
          </p>
          <p style={{ fontSize: 'var(--font-size-xs)', color: 'var(--text-tertiary)' }}>
            Supported types: Flowchart, Sequence, Class, State, ER, Gantt, Pie
          </p>
          <button
            className="btn btn-secondary"
            style={{ marginTop: 'var(--space-sm)' }}
            onClick={() => setShowEditor(true)}
          >
            Open Editor
          </button>
        </div>
      </div>
    );
  }

  const matchingTypes = diagramCode
    ? DIAGRAM_TYPES.filter((t) =>
        diagramCode.trim().toLowerCase().startsWith(t.keyword.toLowerCase()),
      )
    : [];

  return (
    <div className="mermaid-diagram-view">
      <div className="diagram-toolbar">
        <div className="diagram-toolbar-left">
          <h3>Diagram</h3>
          {matchingTypes.length > 0 && (
            <div className="diagram-presets">
              {matchingTypes.map((t) => (
                <span key={t.label} className="provider-badge">
                  {t.label}
                </span>
              ))}
            </div>
          )}
          {/* Dropdown selector or single label */}
          {diagrams.length > 1 ? (
            <select
              value={selectedIndex}
              onChange={(e) => setSelectedIndex(Number(e.target.value))}
              style={{
                marginLeft: 'var(--space-sm)',
                background: 'var(--bg-tertiary)',
                color: 'var(--text-primary)',
                border: '1px solid var(--border-secondary)',
                borderRadius: 4,
                padding: '2px 6px',
                fontSize: 'var(--font-size-xs)',
              }}
            >
              {diagrams.map((d, i) => (
                <option key={i} value={i}>{diagramOptionLabel(d, i)}</option>
              ))}
            </select>
          ) : selectedDiagram ? (
            <span style={{ fontSize: 'var(--font-size-xs)', color: 'var(--text-tertiary)', marginLeft: 'var(--space-sm)' }}>
              {diagramOptionLabel(selectedDiagram, 0)}
            </span>
          ) : null}
        </div>
        <div className="diagram-toolbar-right">
          <button
            className={`btn btn-ghost btn-sm ${showEditor ? 'active' : ''}`}
            onClick={() => setShowEditor(!showEditor)}
          >
            {showEditor ? 'Hide Editor' : 'Edit'}
          </button>
        </div>
      </div>

      <div className={`diagram-body ${showEditor ? 'with-editor' : ''}`}>
        <div className="diagram-canvas">
          {error ? (
            <div className="diagram-error">
              <svg width="24" height="24" viewBox="0 0 16 16" fill="currentColor">
                <path d="M6.457 1.047c.659-1.234 2.427-1.234 3.086 0l6.082 11.378A1.75 1.75 0 0114.082 15H1.918a1.75 1.75 0 01-1.543-2.575zM8 5a.75.75 0 00-.75.75v2.5a.75.75 0 001.5 0v-2.5A.75.75 0 008 5zm1 6a1 1 0 11-2 0 1 1 0 012 0z" />
              </svg>
              <p>Failed to render diagram</p>
              <pre className="diagram-error-detail">{error}</pre>
            </div>
          ) : (
            <div className="diagram-rendered" ref={containerRef} />
          )}
        </div>

        {showEditor && (
          <div className="diagram-editor">
            <textarea
              className="diagram-code-input"
              value={diagramCode ?? ''}
              onChange={(e) => setDiagramCode(e.target.value || null)}
              spellCheck={false}
              placeholder="Enter Mermaid diagram code..."
            />
          </div>
        )}
      </div>
    </div>
  );
};
