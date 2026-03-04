import React, { useState, useEffect } from 'react';
import { Sidebar } from './Sidebar';
import { DetailPanel } from './DetailPanel';
import { useWebSocket } from '@/hooks/useWebSocket';
import { useKeyboard } from '@/hooks/useKeyboard';
import { useTheme } from '@/hooks/useTheme';
import { useSessions } from '@/hooks/useSessions';
import { useSessionsStore } from '@/store/sessions';
import { useStatsStore } from '@/store/stats';
import { useSearchStore } from '@/store/search';
import { CommandPalette } from '@/components/search/CommandPalette';
import { GlobalStatsMenu } from '@/components/stats/GlobalStatsMenu';

export type DetailView =
  | 'session'
  | 'terminal'
  | 'changes'
  | 'plan'
  | 'diagram'
  | 'settings'
  | 'launcher';

const VIEW_TABS: { key: DetailView; label: string }[] = [
  { key: 'session', label: 'Session' },
  { key: 'terminal', label: 'Terminal' },
  { key: 'changes', label: 'Changes' },
  { key: 'plan', label: 'Plan' },
  { key: 'diagram', label: 'Diagram' },
  { key: 'launcher', label: 'Launch' },
  { key: 'settings', label: 'Settings' },
];

export const AppLayout: React.FC = () => {
  // Initialize hooks
  const { connected } = useWebSocket();
  useKeyboard();
  useTheme();

  const sessionData = useSessions();

  const fetchRepositories = useSessionsStore((s) => s.fetchRepositories);
  const fetchStats = useStatsStore((s) => s.fetchStats);
  const toggleSearch = useSearchStore((s) => s.toggle);

  // Fetch repositories and stats on mount
  useEffect(() => {
    fetchRepositories();
    fetchStats('claude');
  }, [fetchRepositories, fetchStats]);

  const [activeView, setActiveView] = useState<DetailView>('session');
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);

  return (
    <div className="app-layout">
      <header className="app-header">
        <div className="header-left">
          <button
            className="sidebar-toggle"
            onClick={() => setSidebarCollapsed(!sidebarCollapsed)}
            title={sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
              <rect x="2" y="3" width="12" height="1.5" rx="0.5" />
              <rect x="2" y="7.25" width="12" height="1.5" rx="0.5" />
              <rect x="2" y="11.5" width="12" height="1.5" rx="0.5" />
            </svg>
          </button>
          <h1 className="app-title">AgentHub</h1>
          <span className="app-badge">Linux</span>
        </div>
        <div className="header-center">
          <nav className="view-tabs">
            {VIEW_TABS.map(({ key, label }) => (
              <button
                key={key}
                className={`view-tab ${activeView === key ? 'active' : ''}`}
                onClick={() => setActiveView(key)}
              >
                {label}
              </button>
            ))}
          </nav>
        </div>
        <div className="header-right">
          <button
            className="search-trigger"
            onClick={() => toggleSearch()}
            title="Search (Ctrl+K)"
          >
            <svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor">
              <path d="M11.742 10.344a6.5 6.5 0 1 0-1.397 1.398h-.001c.03.04.062.078.098.115l3.85 3.85a1 1 0 0 0 1.415-1.414l-3.85-3.85a1.007 1.007 0 0 0-.115-.1zM12 6.5a5.5 5.5 0 1 1-11 0 5.5 5.5 0 0 1 11 0z" />
            </svg>
            <span className="search-shortcut">Ctrl+K</span>
          </button>
          <GlobalStatsMenu />
          <div
            className={`connection-status ${connected ? 'connected' : 'disconnected'}`}
          >
            <span className="status-dot" />
            {connected ? 'Connected' : 'Disconnected'}
          </div>
        </div>
      </header>

      <div className="app-body">
        <Sidebar
          collapsed={sidebarCollapsed}
          sessionData={sessionData}
        />
        <DetailPanel
          activeView={activeView}
          sessionData={sessionData}
          onChangeView={setActiveView}
        />
      </div>

      <CommandPalette />
    </div>
  );
};
