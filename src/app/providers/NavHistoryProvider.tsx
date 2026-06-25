// src/app/providers/NavHistoryProvider.tsx
import { createContext, type ReactNode } from 'react';

export interface NavHistoryContextValue {
  canBack: boolean;
  canForward: boolean;
  back: () => void;
  forward: () => void;
}

export const NavHistoryContext = createContext<NavHistoryContextValue | null>(null);

interface NavHistoryProviderProps {
  children: ReactNode;
}

export function NavHistoryProvider({ children }: NavHistoryProviderProps) {
  const value: NavHistoryContextValue = {
    canBack: false,
    canForward: false,
    back: () => {},
    forward: () => {},
  };
  return <NavHistoryContext.Provider value={value}>{children}</NavHistoryContext.Provider>;
}
