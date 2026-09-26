import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react';

import { DENSITY_DEFAULT, normalizeDensityMode, type DensityMode } from './densityMode';
import { loadDensity, saveDensity } from './densityStorage';

interface DensityContextValue {
  density: DensityMode;
  setDensity: (mode: DensityMode) => void;
}

const DensityContext = createContext<DensityContextValue | null>(null);

function applyDensityAttribute(mode: DensityMode): void {
  document.documentElement.setAttribute('data-density', mode);
}

export function DensityProvider({ children }: { children: ReactNode }) {
  const [density, setDensityState] = useState<DensityMode>(DENSITY_DEFAULT);

  useEffect(() => {
    const initial = normalizeDensityMode(loadDensity());
    setDensityState(initial);
    applyDensityAttribute(initial);
  }, []);

  const setDensity = useCallback((mode: DensityMode) => {
    const next = normalizeDensityMode(mode);
    setDensityState(next);
    saveDensity(next);
    applyDensityAttribute(next);
  }, []);

  return (
    <DensityContext.Provider value={{ density, setDensity }}>
      {children}
    </DensityContext.Provider>
  );
}

export function useDensity(): DensityContextValue {
  const ctx = useContext(DensityContext);
  if (!ctx) throw new Error('useDensity requires DensityProvider');
  return ctx;
}
