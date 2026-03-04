import { create } from 'zustand';
import { api } from '@/api/client';

export interface ProviderInfo {
  key: string;
  label: string;
  color: string;
  available: boolean;
  path: string | null;
}

interface ProvidersState {
  providers: ProviderInfo[];
  loaded: boolean;
  fetchProviders: () => Promise<void>;
}

const GREY = '#6b7280';

export const useProvidersStore = create<ProvidersState>((set, get) => ({
  providers: [],
  loaded: false,

  fetchProviders: async () => {
    if (get().loaded) return;
    try {
      const entries = await api.settings.cliStatus();
      if (entries.length > 0) {
        set({
          providers: entries.map((e) => ({
            key: e.key,
            label: e.label,
            color: e.available ? e.color : GREY,
            available: e.available,
            path: e.path,
          })),
          loaded: true,
        });
      }
    } catch {
      // Keep empty until next attempt
    }
  },
}));
