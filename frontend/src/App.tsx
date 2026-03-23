import React, { useEffect } from 'react';
import { AppLayout } from '@/components/layout/AppLayout';
import { requestNotificationPermission } from '@/lib/notifications';
import './App.css';

const App: React.FC = () => {
  useEffect(() => {
    requestNotificationPermission();
  }, []);

  return <AppLayout />;
};

export default App;
