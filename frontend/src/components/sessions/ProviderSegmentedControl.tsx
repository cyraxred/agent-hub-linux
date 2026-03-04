import React, { useEffect } from 'react';
import { useSessionsStore } from '@/store/sessions';
import { useProvidersStore } from '@/store/providers';

export const ProviderSegmentedControl: React.FC = () => {
  const activeProvider = useSessionsStore((s) => s.activeProvider);
  const setActiveProvider = useSessionsStore((s) => s.setActiveProvider);
  const repositories = useSessionsStore((s) => s.repositories);
  const { providers, fetchProviders } = useProvidersStore();

  useEffect(() => {
    fetchProviders();
  }, [fetchProviders]);

  const repoCount = repositories.length;

  return (
    <div className="provider-segments">
      {providers.map(({ key, label, color, available }) => {
        const isActive = activeProvider === key;

        return (
          <button
            key={key}
            className={`provider-segment ${isActive ? 'active' : ''}`}
            onClick={() => setActiveProvider(key)}
            style={isActive ? { borderColor: color } : undefined}
            title={available ? label : `${label} CLI not found`}
          >
            <span className="provider-color-dot" style={{ backgroundColor: color }} />
            <span>{label}</span>
            {isActive && (
              <span className="provider-count">{repoCount}</span>
            )}
          </button>
        );
      })}
    </div>
  );
};
