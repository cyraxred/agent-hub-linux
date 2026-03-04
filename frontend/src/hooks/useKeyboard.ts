import { useEffect } from 'react';
import { useSearchStore } from '@/store/search';

export function useKeyboard() {
  const toggle = useSearchStore((s) => s.toggle);
  const close = useSearchStore((s) => s.close);
  const isOpen = useSearchStore((s) => s.isOpen);
  const selectNext = useSearchStore((s) => s.selectNext);
  const selectPrev = useSearchStore((s) => s.selectPrev);

  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      // Ctrl+K or Cmd+K to toggle command palette
      if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        e.preventDefault();
        toggle();
        return;
      }

      // Escape to close
      if (e.key === 'Escape' && isOpen) {
        e.preventDefault();
        close();
        return;
      }

      // Arrow navigation in command palette
      if (isOpen) {
        if (e.key === 'ArrowDown') {
          e.preventDefault();
          selectNext();
        } else if (e.key === 'ArrowUp') {
          e.preventDefault();
          selectPrev();
        }
      }
    }

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [toggle, close, isOpen, selectNext, selectPrev]);
}
