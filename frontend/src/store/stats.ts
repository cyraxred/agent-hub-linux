import { create } from 'zustand';
import type { GlobalStatsCache } from '@/types/generated';
import { api } from '@/api/client';

interface StatsState {
  claudeStats: GlobalStatsCache | null;
  codexStats: GlobalStatsCache | null;
  loading: boolean;
  error: string | null;

  fetchStats: (provider?: string) => Promise<void>;
  refreshStats: (provider: string) => Promise<void>;
  /** Called by WS hook when stats_updated arrives. */
  setStats: (provider: string, stats: GlobalStatsCache) => void;
}

export const useStatsStore = create<StatsState>((set) => ({
  claudeStats: null,
  codexStats: null,
  loading: false,
  error: null,

  fetchStats: async (provider = 'claude') => {
    set({ loading: true, error: null });
    try {
      const stats = await api.stats.get(provider);
      if (provider === 'claude') {
        set({ claudeStats: stats, loading: false });
      } else {
        set({ codexStats: stats, loading: false });
      }
    } catch (err) {
      set({ error: (err as Error).message, loading: false });
    }
  },

  refreshStats: async (provider) => {
    set({ error: null });
    try {
      await api.stats.refresh(provider);
      const stats = await api.stats.get(provider);
      if (provider === 'claude') {
        set({ claudeStats: stats });
      } else {
        set({ codexStats: stats });
      }
    } catch (err) {
      set({ error: (err as Error).message });
    }
  },

  setStats: (provider, stats) => {
    if (provider === 'claude') {
      set({ claudeStats: stats });
    } else if (provider === 'codex') {
      set({ codexStats: stats });
    }
  },
}));
