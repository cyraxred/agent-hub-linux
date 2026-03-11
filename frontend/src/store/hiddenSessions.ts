import { create } from 'zustand';

const STORAGE_KEY = 'agenthub:hidden-sessions';

function loadFromStorage(): Set<string> {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) return new Set(JSON.parse(raw) as string[]);
  } catch {
    // ignore
  }
  return new Set();
}

function saveToStorage(ids: Set<string>): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify([...ids]));
  } catch {
    // ignore
  }
}

interface HiddenSessionsState {
  hiddenIds: Set<string>;
  showHidden: boolean;
  recentOnly: boolean;

  hide: (rawId: string) => void;
  unhide: (rawId: string) => void;
  isHidden: (rawId: string) => boolean;
  toggleShowHidden: () => void;
  toggleRecentOnly: () => void;
}

export const useHiddenSessionsStore = create<HiddenSessionsState>((set, get) => ({
  hiddenIds: loadFromStorage(),
  showHidden: false,
  recentOnly: false,

  hide: (rawId) => {
    set((s) => {
      const next = new Set(s.hiddenIds);
      next.add(rawId);
      saveToStorage(next);
      return { hiddenIds: next };
    });
  },

  unhide: (rawId) => {
    set((s) => {
      const next = new Set(s.hiddenIds);
      next.delete(rawId);
      saveToStorage(next);
      return { hiddenIds: next };
    });
  },

  isHidden: (rawId) => get().hiddenIds.has(rawId),

  toggleShowHidden: () => set((s) => ({ showHidden: !s.showHidden })),
  toggleRecentOnly: () => set((s) => ({ recentOnly: !s.recentOnly })),
}));
