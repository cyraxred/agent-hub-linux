/**
 * Auth store — manages PAM authentication state.
 */

import { create } from 'zustand';

interface AuthState {
  authenticated: boolean;
  username: string | null;
  loading: boolean;
  error: string | null;

  checkAuthStatus: () => Promise<void>;
  login: (username: string, password: string) => Promise<boolean>;
  logout: () => Promise<void>;
  invalidateAllTokens: () => Promise<number>;
}

export const useAuthStore = create<AuthState>((set) => ({
  authenticated: false,
  username: null,
  loading: true,
  error: null,

  checkAuthStatus: async () => {
    try {
      const res = await fetch('/api/auth/status', { credentials: 'same-origin' });
      const data = await res.json();
      set({
        authenticated: data.authenticated,
        username: data.username ?? null,
        loading: false,
      });
    } catch {
      // If status check fails (e.g. server not ready), keep loading
      set({ loading: false, authenticated: false });
    }
  },

  login: async (username: string, password: string) => {
    set({ error: null });
    try {
      const res = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
        credentials: 'same-origin',
      });
      if (!res.ok) {
        const data = await res.json();
        set({ error: data.detail || 'Login failed' });
        return false;
      }
      set({ authenticated: true, username, error: null });
      return true;
    } catch (err) {
      set({ error: (err as Error).message });
      return false;
    }
  },

  logout: async () => {
    await fetch('/api/auth/logout', { method: 'POST', credentials: 'same-origin' }).catch(
      () => {},
    );
    set({ authenticated: false, username: null });
  },

  invalidateAllTokens: async () => {
    const res = await fetch('/api/auth/invalidate-all', {
      method: 'POST',
      credentials: 'same-origin',
    });
    const data = await res.json();
    set({ authenticated: false, username: null });
    return data.tokens_invalidated ?? 0;
  },
}));
