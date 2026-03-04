import { create } from 'zustand';
import type { SessionSearchResult } from '@/types/generated';
import { api } from '@/api/client';

interface SearchState {
  query: string;
  results: SessionSearchResult[];
  isOpen: boolean;
  loading: boolean;
  error: string | null;
  selectedIndex: number;

  setQuery: (query: string) => void;
  search: (query: string, provider?: string) => Promise<void>;
  open: () => void;
  close: () => void;
  toggle: () => void;
  selectNext: () => void;
  selectPrev: () => void;
  setSelectedIndex: (index: number) => void;
  getSelected: () => SessionSearchResult | undefined;
  clear: () => void;
  reindex: (provider?: string) => Promise<void>;
}

export const useSearchStore = create<SearchState>((set, get) => ({
  query: '',
  results: [],
  isOpen: false,
  loading: false,
  error: null,
  selectedIndex: 0,

  setQuery: (query) => {
    set({ query });
    if (query.trim().length >= 2) {
      get().search(query);
    } else {
      set({ results: [], selectedIndex: 0 });
    }
  },

  search: async (query, provider = 'claude') => {
    set({ loading: true, error: null });
    try {
      const results = await api.search.query(query, provider);
      set({ results, loading: false, selectedIndex: 0 });
    } catch (err) {
      set({ results: [], loading: false, error: (err as Error).message });
    }
  },

  open: () => set({ isOpen: true, query: '', results: [], selectedIndex: 0 }),
  close: () => set({ isOpen: false, query: '', results: [], selectedIndex: 0 }),
  toggle: () => {
    if (get().isOpen) get().close();
    else get().open();
  },

  selectNext: () =>
    set((s) => ({ selectedIndex: Math.min(s.selectedIndex + 1, s.results.length - 1) })),
  selectPrev: () =>
    set((s) => ({ selectedIndex: Math.max(s.selectedIndex - 1, 0) })),
  setSelectedIndex: (index) => set({ selectedIndex: index }),
  getSelected: () => {
    const { results, selectedIndex } = get();
    return results[selectedIndex];
  },
  clear: () => set({ query: '', results: [], selectedIndex: 0 }),

  reindex: async (provider) => {
    set({ error: null });
    try {
      await api.search.reindex(provider);
    } catch (err) {
      set({ error: (err as Error).message });
    }
  },
}));
