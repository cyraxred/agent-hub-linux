import { create } from 'zustand';
import { api } from '@/api/client';

interface SettingsState {
  settings: Record<string, unknown>;
  loading: boolean;
  error: string | null;
  dirty: boolean;

  fetchSettings: () => Promise<void>;
  updateSettings: (updates: Record<string, unknown>) => void;
  saveSettings: () => Promise<void>;
}

export const useSettingsStore = create<SettingsState>((set, get) => ({
  settings: {},
  loading: false,
  error: null,
  dirty: false,

  fetchSettings: async () => {
    set({ loading: true, error: null });
    try {
      const settings = await api.settings.get();
      set({ settings, loading: false });
    } catch (err) {
      set({ loading: false, error: (err as Error).message });
    }
  },

  updateSettings: (updates) => {
    set((s) => ({
      settings: { ...s.settings, ...updates },
      dirty: true,
    }));
  },

  saveSettings: async () => {
    const { settings } = get();
    set({ loading: true, error: null });
    try {
      const saved = await api.settings.update(settings);
      set({ settings: saved, loading: false, dirty: false });
    } catch (err) {
      set({ error: (err as Error).message, loading: false });
    }
  },
}));
