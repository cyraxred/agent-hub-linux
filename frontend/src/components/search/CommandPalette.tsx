import { SessionId } from '@/types/session';
import React, { useRef, useEffect, useCallback } from 'react';
import { useSearchStore } from '@/store/search';
import { useSessionsStore } from '@/store/sessions';
import { SearchResultRow } from './SearchResultRow';

export const CommandPalette: React.FC = () => {
  const {
    query,
    results,
    isOpen,
    loading,
    selectedIndex,
    setQuery,
    close,
    selectNext,
    selectPrev,
    getSelected,
    setSelectedIndex,
  } = useSearchStore();

  const selectSession = useSessionsStore((s) => s.selectSession);

  const inputRef = useRef<HTMLInputElement>(null);
  const backdropRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (isOpen && inputRef.current) {
      inputRef.current.focus();
    }
  }, [isOpen]);

  const executeSelected = useCallback(() => {
    const selected = getSelected();
    if (selected) {
      selectSession(SessionId.local(selected.id));
      close();
    }
  }, [getSelected, selectSession, close]);

  if (!isOpen) return null;

  const handleKeyDown = (e: React.KeyboardEvent) => {
    switch (e.key) {
      case 'ArrowDown':
        e.preventDefault();
        selectNext();
        break;
      case 'ArrowUp':
        e.preventDefault();
        selectPrev();
        break;
      case 'Enter':
        e.preventDefault();
        executeSelected();
        break;
      case 'Escape':
        e.preventDefault();
        close();
        break;
    }
  };

  const handleBackdropClick = (e: React.MouseEvent) => {
    if (e.target === backdropRef.current) {
      close();
    }
  };

  const handleResultClick = (index: number) => {
    setSelectedIndex(index);
    const selected = results[index];
    if (selected) {
      selectSession(SessionId.local(selected.id));
      close();
    }
  };

  return (
    <div className="command-palette-backdrop" ref={backdropRef} onClick={handleBackdropClick}>
      <div className="command-palette" role="dialog" aria-label="Command palette">
        <div className="command-palette-header">
          <svg className="search-icon" width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
            <path d="M11.742 10.344a6.5 6.5 0 1 0-1.397 1.398h-.001c.03.04.062.078.098.115l3.85 3.85a1 1 0 0 0 1.415-1.414l-3.85-3.85a1.007 1.007 0 0 0-.115-.1zM12 6.5a5.5 5.5 0 1 1-11 0 5.5 5.5 0 0 1 11 0z" />
          </svg>
          <input
            ref={inputRef}
            className="command-palette-input"
            type="text"
            placeholder="Search sessions, repositories, commands..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={handleKeyDown}
            aria-autocomplete="list"
            aria-controls="search-results"
            role="combobox"
            aria-expanded={results.length > 0}
          />
          {loading && <div className="spinner spinner-sm" />}
          <kbd className="palette-shortcut">ESC</kbd>
        </div>

        <div className="command-palette-body" id="search-results" role="listbox">
          {query.length === 0 ? (
            <div className="palette-hints">
              <div className="palette-hint">
                <span className="hint-label">Search</span>
                <span className="hint-desc">Type to search sessions, repositories, and files</span>
              </div>
              <div className="palette-hint">
                <span className="hint-label">Navigate</span>
                <span className="hint-desc">
                  <kbd>Up</kbd> <kbd>Down</kbd> to navigate, <kbd>Enter</kbd> to select
                </span>
              </div>
            </div>
          ) : results.length === 0 && !loading ? (
            <div className="palette-no-results">
              <p>No results for &ldquo;{query}&rdquo;</p>
            </div>
          ) : (
            <div className="palette-results">
              {results.map((result, index) => (
                <SearchResultRow
                  key={`${result.matched_field}-${result.id}`}
                  result={result}
                  isSelected={index === selectedIndex}
                  onClick={() => handleResultClick(index)}
                />
              ))}
            </div>
          )}
        </div>

        <div className="command-palette-footer">
          <span className="palette-footer-hint">
            <kbd>Enter</kbd> to select
          </span>
          <span className="palette-footer-hint">
            <kbd>Esc</kbd> to close
          </span>
        </div>
      </div>
    </div>
  );
};
