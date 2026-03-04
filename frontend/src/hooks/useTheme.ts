import { useEffect } from 'react';
import { useSettingsStore } from '@/store/settings';

export function useTheme() {
  const theme = useSettingsStore((s) => s.settings.theme) as
    | 'dark'
    | 'light'
    | 'system'
    | undefined;

  useEffect(() => {
    const root = document.documentElement;
    const resolved = theme ?? 'dark';

    if (resolved === 'system') {
      const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
      root.setAttribute('data-theme', prefersDark ? 'dark' : 'light');

      const handler = (e: MediaQueryListEvent) => {
        root.setAttribute('data-theme', e.matches ? 'dark' : 'light');
      };
      const mql = window.matchMedia('(prefers-color-scheme: dark)');
      mql.addEventListener('change', handler);
      return () => mql.removeEventListener('change', handler);
    } else {
      root.setAttribute('data-theme', resolved);
    }
  }, [theme]);

  return theme ?? 'dark';
}
