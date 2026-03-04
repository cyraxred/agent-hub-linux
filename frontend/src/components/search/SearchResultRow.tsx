import React from 'react';
import type { SessionSearchResult, SearchMatchField } from '@/types/generated';

interface SearchResultRowProps {
  result: SessionSearchResult;
  isSelected: boolean;
  onClick: () => void;
}

const fieldIcons: Record<SearchMatchField, React.ReactNode> = {
  slug: (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
      <path d="M1 7.775V2.75C1 1.784 1.784 1 2.75 1h5.025c.464 0 .91.184 1.238.513l6.25 6.25a1.75 1.75 0 010 2.474l-5.026 5.026a1.75 1.75 0 01-2.474 0l-6.25-6.25A1.752 1.752 0 011 7.775zM6 5a1 1 0 10-2 0 1 1 0 002 0z" />
    </svg>
  ),
  path: (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
      <path d="M1.75 1A1.75 1.75 0 000 2.75v10.5C0 14.216.784 15 1.75 15h12.5A1.75 1.75 0 0016 13.25v-8.5A1.75 1.75 0 0014.25 3H7.5a.25.25 0 01-.2-.1l-.9-1.2C6.07 1.26 5.55 1 5 1H1.75z" />
    </svg>
  ),
  git_branch: (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
      <path d="M11.75 2.5a.75.75 0 100 1.5.75.75 0 000-1.5zm-2.25.75a2.25 2.25 0 113 2.122V6A2.5 2.5 0 0110 8.5H6a1 1 0 00-1 1v1.128a2.251 2.251 0 11-1.5 0V5.372a2.25 2.25 0 111.5 0v1.836A2.492 2.492 0 016 7h4a1 1 0 001-1v-.628A2.25 2.25 0 019.5 3.25zM4.25 12a.75.75 0 100 1.5.75.75 0 000-1.5zM3.5 3.25a.75.75 0 111.5 0 .75.75 0 01-1.5 0z" />
    </svg>
  ),
  first_message: (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
      <path d="M1.5 1.75C1.5.784 2.284 0 3.25 0h9.5C13.716 0 14.5.784 14.5 1.75v9.5A1.75 1.75 0 0112.75 13H8.06l-2.573 2.573A1.458 1.458 0 013 14.543V13H1.75A1.75 1.75 0 010 11.25v-9.5C0 .784.784 0 1.75 0h.25z" />
    </svg>
  ),
  summary: (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
      <path d="M3.75 1.5a.25.25 0 00-.25.25v11.5c0 .138.112.25.25.25h8.5a.25.25 0 00.25-.25V6H9.75A1.75 1.75 0 018 4.25V1.5H3.75zm5.75.56v2.19c0 .138.112.25.25.25h2.19L9.5 2.06zM2 1.75C2 .784 2.784 0 3.75 0h5.086c.464 0 .909.184 1.237.513l3.414 3.414c.329.328.513.773.513 1.237v8.086A1.75 1.75 0 0112.25 15h-8.5A1.75 1.75 0 012 13.25V1.75z" />
    </svg>
  ),
};

function getRelevanceIndicator(score?: number): React.ReactNode {
  if (score == null) return null;
  const dots = Math.max(1, Math.min(5, Math.round(score * 5)));
  return (
    <span className="search-result-type-badge" title={`Relevance: ${(score * 100).toFixed(0)}%`}>
      {'*'.repeat(dots)}
    </span>
  );
}

export const SearchResultRow: React.FC<SearchResultRowProps> = ({
  result,
  isSelected,
  onClick,
}) => {
  return (
    <div
      className={`search-result-row ${isSelected ? 'selected' : ''}`}
      onClick={onClick}
      role="option"
      aria-selected={isSelected}
    >
      <div className="search-result-icon">
        {fieldIcons[result.matched_field]}
      </div>
      <div className="search-result-content">
        <span className="search-result-title">
          {result.matched_text || result.slug || result.first_message || result.id}
        </span>
        <span className="search-result-subtitle">
          {result.project_path ?? ''}
        </span>
      </div>
      <div className="search-result-type">
        {getRelevanceIndicator(result.relevance_score)}
      </div>
      {isSelected && (
        <div className="search-result-hint">
          <kbd>Enter</kbd>
        </div>
      )}
    </div>
  );
};
