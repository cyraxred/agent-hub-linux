import { SessionId } from '@/types/session';
import { useCallback } from 'react';
import { useSearchStore } from '@/store/search';
import { useSessionsStore } from '@/store/sessions';

export function useSearch() {
  const {
    query,
    results,
    isOpen,
    loading,
    error,
    selectedIndex,
    setQuery,
    open,
    close,
    toggle,
    selectNext,
    selectPrev,
    setSelectedIndex,
    getSelected,
    clear,
    reindex,
  } = useSearchStore();

  const selectSession = useSessionsStore((s) => s.selectSession);

  const executeSelected = useCallback(() => {
    const selected = getSelected();
    if (!selected) return;

    // Select the session in the sessions store by its id
    selectSession(SessionId.local(selected.id));

    close();
  }, [getSelected, selectSession, close]);

  return {
    query,
    results,
    isOpen,
    loading,
    error,
    selectedIndex,
    setQuery,
    open,
    close,
    toggle,
    selectNext,
    selectPrev,
    setSelectedIndex,
    getSelected,
    executeSelected,
    clear,
    reindex,
  };
}
