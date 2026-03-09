import React, { useCallback, useEffect, useState } from 'react';
import { api } from '@/api/client';
import { historyAppendBus } from '@/store/sessions';
import type { SessionHistoryEntry } from '@/types/generated';

interface HistoryEntry {
  line: number;
  type: string;
  data: Record<string, unknown>;
}

interface SessionHistoryViewProps {
  sessionId: string;
  /** When true, subscribe to WS-pushed history entries from the file watcher. */
  isMonitored?: boolean;
}

const TYPE_COLORS: Record<string, string> = {
  system: 'var(--accent-purple)',
  user: 'var(--accent-blue)',
  assistant: 'var(--accent-green)',
  tool_use: 'var(--accent-cyan, var(--accent-blue))',
  tool_result: 'var(--accent-orange)',
  progress: 'var(--accent-yellow)',
  summary: 'var(--accent-orange)',
  'file-history-snapshot': 'var(--text-tertiary)',
  'queue-operation': 'var(--text-tertiary)',
};

const PAGE_SIZE = 50;

export const SessionHistoryView: React.FC<SessionHistoryViewProps> = ({ sessionId, isMonitored }) => {
  const [entries, setEntries] = useState<HistoryEntry[]>([]);
  const [totalLines, setTotalLines] = useState(0);
  const [loading, setLoading] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expandedLines, setExpandedLines] = useState<Set<number>>(new Set());
  const [typeFilter, setTypeFilter] = useState<string | null>(null);

  const loadPage = useCallback(
    async (offset: number, append: boolean) => {
      setLoading(true);
      setError(null);
      try {
        const resp = await api.sessions.history(sessionId, offset, PAGE_SIZE);
        setTotalLines(resp.total_lines);
        setHasMore(resp.has_more);
        if (append) {
          setEntries((prev) => [...prev, ...resp.entries]);
        } else {
          setEntries(resp.entries);
        }
      } catch (err) {
        setError((err as Error).message);
      } finally {
        setLoading(false);
      }
    },
    [sessionId],
  );

  // Initial load when session changes
  useEffect(() => {
    setEntries([]);
    setExpandedLines(new Set());
    setTypeFilter(null);
    loadPage(0, false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  // Subscribe to WS-pushed history entries from the file watcher.
  // New entries are prepended (newest-first) with no file re-read.
  useEffect(() => {
    if (!isMonitored) return;
    return historyAppendBus.subscribe(
      (sid: string, newEntries: SessionHistoryEntry[], newTotal: number) => {
        if (sid !== sessionId) return;
        setTotalLines(newTotal);
        setEntries((prev) => {
          // Deduplicate by line number — new entries go to the front (newest-first)
          const existingLines = new Set(prev.map((e) => e.line));
          const fresh = newEntries
            .filter((e) => !existingLines.has(e.line))
            .map((e) => ({ line: e.line, type: e.type, data: e.data as Record<string, unknown> }));
          if (fresh.length === 0) return prev;
          // newest-first: prepend, then truncate to PAGE_SIZE
          const merged = [...fresh.reverse(), ...prev];
          return merged.slice(0, PAGE_SIZE);
        });
      },
    );
  }, [isMonitored, sessionId]);

  const handleLoadMore = () => {
    loadPage(entries.length, true);
  };

  const toggleExpand = (line: number) => {
    setExpandedLines((prev) => {
      const next = new Set(prev);
      if (next.has(line)) {
        next.delete(line);
      } else {
        next.add(line);
      }
      return next;
    });
  };

  // Collect unique types for filter
  const uniqueTypes = Array.from(new Set(entries.map((e) => e.type))).sort();

  const filtered = typeFilter ? entries.filter((e) => e.type === typeFilter) : entries;

  return (
    <div className="session-history-view">
      <div className="history-toolbar">
        <span className="history-summary">
          {totalLines} entries
          {typeFilter && <> &middot; filtered: <strong>{typeFilter}</strong></>}
        </span>
        <div className="history-filters">
          <button
            className={`btn btn-ghost btn-xs ${typeFilter === null ? 'active' : ''}`}
            onClick={() => setTypeFilter(null)}
          >
            All
          </button>
          {uniqueTypes.map((t) => (
            <button
              key={t}
              className={`btn btn-ghost btn-xs ${typeFilter === t ? 'active' : ''}`}
              onClick={() => setTypeFilter(typeFilter === t ? null : t)}
            >
              {t}
            </button>
          ))}
        </div>
      </div>

      {error && <div className="history-error">{error}</div>}

      <div className="history-entries">
        {filtered.map((entry) => {
          const isExpanded = expandedLines.has(entry.line);
          const displayType = getDisplayType(entry.type, entry.data);
          const color = TYPE_COLORS[displayType] ?? TYPE_COLORS[entry.type] ?? 'var(--text-secondary)';

          return (
            <div key={entry.line} className="history-entry">
              <div
                className="history-entry-header"
                onClick={() => toggleExpand(entry.line)}
              >
                <span className="history-expand-icon">
                  {isExpanded ? '\u25BC' : '\u25B6'}
                </span>
                <span className="history-line-num">#{entry.line}</span>
                <span
                  className="history-type-badge"
                  style={{ color }}
                >
                  {displayType}
                </span>
                <span className="history-preview">
                  {getPreview(entry.data)}
                </span>
              </div>
              {isExpanded && (
                <pre className="history-json">
                  {JSON.stringify(entry.data, null, 2)}
                </pre>
              )}
            </div>
          );
        })}
      </div>

      {hasMore && (
        <div className="history-load-more">
          <button
            className="btn btn-secondary"
            onClick={handleLoadMore}
            disabled={loading}
          >
            {loading ? 'Loading...' : `Load Older (${entries.length} / ${totalLines})`}
          </button>
        </div>
      )}

      {!hasMore && entries.length > 0 && (
        <div className="history-end">End of history</div>
      )}

      {!loading && entries.length === 0 && !error && (
        <div className="detail-empty">
          <h3>No History</h3>
          <p>No JSONL entries found for this session.</p>
        </div>
      )}
    </div>
  );
};

/** Determine a more specific display type for the entry (e.g. tool_use, tool_result). */
function getDisplayType(entryType: string, data: Record<string, unknown>): string {
  const msg = data.message as Record<string, unknown> | undefined;
  if (!msg) return entryType;
  const content = msg.content;
  if (!Array.isArray(content)) return entryType;

  // Check first content block for tool_use / tool_result
  for (const block of content) {
    if (typeof block === 'object' && block !== null) {
      const b = block as Record<string, unknown>;
      if (b.type === 'tool_use') return 'tool_use';
      if (b.type === 'tool_result') return 'tool_result';
    }
  }
  return entryType;
}

function getPreview(data: Record<string, unknown>): string {
  const msg = data.message as Record<string, unknown> | undefined;
  if (msg) {
    const content = msg.content;
    if (typeof content === 'string') {
      return content.slice(0, 80);
    }
    if (Array.isArray(content)) {
      for (const block of content) {
        if (typeof block === 'object' && block !== null) {
          const b = block as Record<string, unknown>;
          if (b.type === 'text' && typeof b.text === 'string') {
            return b.text.slice(0, 80);
          }
          if (b.type === 'tool_use') {
            const id = String(b.id ?? '');
            return id ? `${b.name} [${id}]` : String(b.name ?? '');
          }
          if (b.type === 'tool_result') {
            return String(b.tool_use_id ?? '');
          }
        }
      }
      return `[${content.length} blocks]`;
    }
  }

  const type = data.type as string | undefined;
  if (type === 'file-history-snapshot') {
    return 'file snapshot';
  }

  return '';
}
