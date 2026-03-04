import React from 'react';

interface ContextWindowBarProps {
  inputTokens: number;
  outputTokens: number;
  cacheReadTokens: number;
  cacheCreationTokens: number;
  maxTokens?: number;
  compact?: boolean;
}

function formatK(n: number): string {
  return Math.round(n / 1000).toString();
}

export const ContextWindowBar: React.FC<ContextWindowBarProps> = ({
  inputTokens,
  outputTokens,
  cacheReadTokens,
  cacheCreationTokens,
  maxTokens = 200000,
  compact = false,
}) => {
  const totalUsed = inputTokens + outputTokens + cacheReadTokens + cacheCreationTokens;
  const usedPercent = maxTokens > 0 ? (totalUsed / maxTokens) * 100 : 0;

  const inputPercent = maxTokens > 0 ? (inputTokens / maxTokens) * 100 : 0;
  const outputPercent = maxTokens > 0 ? (outputTokens / maxTokens) * 100 : 0;
  const cacheReadPercent = maxTokens > 0 ? (cacheReadTokens / maxTokens) * 100 : 0;
  const cacheCreationPercent = maxTokens > 0 ? (cacheCreationTokens / maxTokens) * 100 : 0;

  const dangerLevel = usedPercent > 90 ? 'critical' : usedPercent > 75 ? 'warning' : 'normal';

  const totalK = formatK(totalUsed);
  const maxK = formatK(maxTokens);
  const pct = Math.round(usedPercent);

  return (
    <div className={`context-window-bar ${compact ? 'compact' : ''} ${dangerLevel}`}>
      <div className="context-bar-header">
        {!compact && <span className="context-bar-title">Context Window</span>}
        <span className="context-bar-usage">
          ~{totalK}K / {maxK}K (~{pct}%)
        </span>
      </div>
      <div className="context-bar-track">
        <div
          className="context-bar-segment input"
          style={{ width: `${inputPercent}%` }}
          title={`Input: ${inputTokens.toLocaleString()}`}
        />
        <div
          className="context-bar-segment output"
          style={{ width: `${outputPercent}%` }}
          title={`Output: ${outputTokens.toLocaleString()}`}
        />
        <div
          className="context-bar-segment cache-read"
          style={{ width: `${cacheReadPercent}%` }}
          title={`Cache Read: ${cacheReadTokens.toLocaleString()}`}
        />
        <div
          className="context-bar-segment cache-write"
          style={{ width: `${cacheCreationPercent}%` }}
          title={`Cache Creation: ${cacheCreationTokens.toLocaleString()}`}
        />
      </div>
      {!compact && (
        <div className="context-bar-legend">
          <div className="legend-item">
            <span className="legend-dot input" />
            <span>Input</span>
          </div>
          <div className="legend-item">
            <span className="legend-dot output" />
            <span>Output</span>
          </div>
          <div className="legend-item">
            <span className="legend-dot cache-read" />
            <span>Cache Read</span>
          </div>
          <div className="legend-item">
            <span className="legend-dot cache-write" />
            <span>Cache Creation</span>
          </div>
        </div>
      )}
    </div>
  );
};
