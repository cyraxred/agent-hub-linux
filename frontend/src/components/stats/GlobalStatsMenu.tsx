import React, { useEffect } from 'react';
import { useStatsStore } from '@/store/stats';
import { StatsPopoverButton } from './StatsPopoverButton';

export const GlobalStatsMenu: React.FC = () => {
  const { claudeStats, fetchStats } = useStatsStore();

  useEffect(() => {
    fetchStats('claude');
  }, [fetchStats]);

  if (!claudeStats) return null;

  return <StatsPopoverButton />;
};
