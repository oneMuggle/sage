import { createContext, useState, useEffect, useRef, type ReactNode } from 'react';
import { useLocation, useNavigate, useNavigationType, NavigationType } from 'react-router-dom';

const MAX_HISTORY = 50;

export interface HistoryEntry {
  path: string;
}

export interface NavHistoryContextValue {
  canBack: boolean;
  canForward: boolean;
  back: () => void;
  forward: () => void;
}

// eslint-disable-next-line react-refresh/only-export-components
export const NavHistoryContext = createContext<NavHistoryContextValue | null>(null);

interface NavHistoryProviderProps {
  children: ReactNode;
}

const buildPath = (location: { pathname: string; search: string; hash: string }) =>
  `${location.pathname}${location.search}${location.hash}`;

export function NavHistoryProvider({ children }: NavHistoryProviderProps) {
  const location = useLocation();
  const navigate = useNavigate();
  const navigationType = useNavigationType();

  const [stack, setStack] = useState<HistoryEntry[]>(() => [{ path: buildPath(location) }]);
  const [cursor, setCursor] = useState(0);

  // skipNextRef prevents duplicate entry from our own back()/forward() navigate calls
  const skipNextRef = useRef(false);

  useEffect(() => {
    if (skipNextRef.current) {
      skipNextRef.current = false;
      return;
    }
    const path = buildPath(location);
    setStack((prevStack) => {
      const prevEntry = prevStack[cursor];
      if (prevEntry && prevEntry.path === path) {
        return prevStack; // Same path as current cursor — no-op
      }
      if (navigationType === NavigationType.Replace) {
        const next = prevStack.slice();
        next[cursor] = { path };
        return next;
      }
      // Discard any forward entries past the cursor, then append.
      const truncated = prevStack.slice(0, cursor + 1);
      truncated.push({ path });
      if (truncated.length > MAX_HISTORY) {
        const overflow = truncated.length - MAX_HISTORY;
        const trimmed = truncated.slice(overflow);
        setCursor(trimmed.length - 1);
        return trimmed;
      }
      setCursor(truncated.length - 1);
      return truncated;
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.pathname, location.search, location.hash, navigationType]);

  const back = () => {
    const next = cursor - 1;
    if (next < 0) return;
    const target = stack[next];
    if (!target) return;
    skipNextRef.current = true;
    setCursor(next);
    void navigate(target.path, { replace: true });
  };

  const forward = () => {
    const next = cursor + 1;
    if (next >= stack.length) return;
    const target = stack[next];
    if (!target) return;
    skipNextRef.current = true;
    setCursor(next);
    void navigate(target.path, { replace: true });
  };

  const value: NavHistoryContextValue = {
    canBack: cursor > 0,
    canForward: cursor < stack.length - 1,
    back,
    forward,
  };
  return <NavHistoryContext.Provider value={value}>{children}</NavHistoryContext.Provider>;
}
