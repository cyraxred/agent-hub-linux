import React, { useEffect } from 'react';
import { AppLayout } from '@/components/layout/AppLayout';
import { LoginPage } from '@/components/auth/LoginPage';
import { useAuthStore } from '@/store/auth';
import { requestNotificationPermission } from '@/lib/notifications';
import './App.css';

const App: React.FC = () => {
  const { authenticated, loading, checkAuthStatus } = useAuthStore();

  useEffect(() => {
    checkAuthStatus();
  }, [checkAuthStatus]);

  useEffect(() => {
    if (authenticated) requestNotificationPermission();
  }, [authenticated]);

  if (loading) {
    return <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100vh', color: 'var(--text-secondary)' }}>Loading...</div>;
  }

  if (!authenticated) {
    return <LoginPage />;
  }

  return <AppLayout />;
};

export default App;
