import React, { useState, useRef, useEffect } from 'react';
import { useStatsStore } from '@/store/stats';
import type { GlobalStatsCache, ModelUsage, DailyActivity } from '@/types/generated';

function formatTokens(n: number): string {
  if (n >= 1_000_000_000) return `${(n / 1_000_000_000).toFixed(1)}B`;
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return n.toString();
}

function formatCost(usd?: number): string {
  if (usd == null || usd === 0) return '$0.00';
  return `$${usd.toFixed(2)}`;
}

function summarizeDailyActivity(daily: DailyActivity[]): string {
  if (!daily || daily.length === 0) return 'No activity data';
  const recent = daily.slice(-7);
  const totalMessages = recent.reduce((s, d) => s + (d.message_count ?? 0), 0);
  const totalSessions = recent.reduce((s, d) => s + (d.session_count ?? 0), 0);
  return `Last 7 days: ${totalSessions} sessions, ${totalMessages} messages`;
}

export const StatsPopoverButton: React.FC = () => {
  const claudeStats = useStatsStore((s) => s.claudeStats);
  const [isOpen, setIsOpen] = useState(false);
  const popoverRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (popoverRef.current && !popoverRef.current.contains(e.target as Node)) {
        setIsOpen(false);
      }
    }

    if (isOpen) {
      document.addEventListener('mousedown', handleClickOutside);
      return () => document.removeEventListener('mousedown', handleClickOutside);
    }
  }, [isOpen]);

  if (!claudeStats) return null;

  const totalSessions = claudeStats.total_sessions ?? 0;
  const totalMessages = claudeStats.total_messages ?? 0;

  // Compute aggregate cost from model_usage
  const modelEntries = Object.entries(claudeStats.model_usage ?? {});
  const totalCost = modelEntries.reduce((sum, [, u]) => sum + (u.cost_usd ?? 0), 0);

  return (
    <div className="stats-popover-container" ref={popoverRef}>
      <button className="stats-trigger" onClick={() => setIsOpen(!isOpen)}>
        <svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor">
          <path d="M1.5 1.75V13.5h13.75a.75.75 0 010 1.5H.75a.75.75 0 01-.75-.75V1.75a.75.75 0 011.5 0zm14.28 2.53l-5.25 5.25a.75.75 0 01-1.06 0L7 7.06 4.28 9.78a.75.75 0 01-1.06-1.06l3.25-3.25a.75.75 0 011.06 0L10 8.06l4.72-4.72a.751.751 0 011.042.018.751.751 0 01.018 1.042z" />
        </svg>
        <span className="stats-trigger-label">{totalSessions} sessions</span>
      </button>

      {isOpen && (
        <div className="stats-popover">
          <div className="stats-popover-header">
            <h4>Global Statistics</h4>
          </div>
          <div className="stats-popover-body">
            {/* Summary grid */}
            <div className="stats-grid">
              <div className="stat-item">
                <span className="stat-item-value">{totalSessions}</span>
                <span className="stat-item-label">Total Sessions</span>
              </div>
              <div className="stat-item">
                <span className="stat-item-value">{formatTokens(totalMessages)}</span>
                <span className="stat-item-label">Total Messages</span>
              </div>
              <div className="stat-item">
                <span className="stat-item-value cost">{formatCost(totalCost)}</span>
                <span className="stat-item-label">Total Cost</span>
              </div>
              <div className="stat-item">
                <span className="stat-item-value">
                  {claudeStats.first_session_date
                    ? new Date(claudeStats.first_session_date).toLocaleDateString()
                    : '--'}
                </span>
                <span className="stat-item-label">First Session</span>
              </div>
            </div>

            {/* Model usage breakdown */}
            {modelEntries.length > 0 && (
              <div className="stats-providers">
                <h5>Model Usage</h5>
                {modelEntries.map(([model, usage]) => (
                  <ModelUsageRow key={model} model={model} usage={usage} />
                ))}
              </div>
            )}

            {/* Daily activity summary */}
            <div className="stats-uptime">
              <span className="uptime-label">Activity</span>
              <span className="uptime-value">
                {summarizeDailyActivity(claudeStats.daily_activity ?? [])}
              </span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

const ModelUsageRow: React.FC<{ model: string; usage: ModelUsage }> = ({ model, usage }) => {
  const inputTokens = usage.input_tokens ?? 0;
  const outputTokens = usage.output_tokens ?? 0;

  return (
    <div className="provider-stat-row">
      <span className="provider-stat-name">{model}</span>
      <span className="provider-stat-count">
        {formatCost(usage.cost_usd)} &middot; {formatTokens(inputTokens)}in / {formatTokens(outputTokens)}out
      </span>
    </div>
  );
};
