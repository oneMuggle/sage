import { useCallback, useMemo, useSyncExternalStore } from 'react';

import {
  displayModeStore,
  getDisplayModeStoreVersion,
  subscribeDisplayModeStore,
} from './displayModeStore';
import {
  getGlobalDisplayModeSnapshot,
  subscribeGlobalDisplayMode,
} from './globalDisplayModePreference';
import { resolveDisplayMode, type DisplayMode } from './resolveDisplayMode';

export function useDisplayMode(sessionId: string | null, messageId: string | null) {
  const storeVersion = useSyncExternalStore(
    subscribeDisplayModeStore,
    getDisplayModeStoreVersion,
    getDisplayModeStoreVersion,
  );
  const globalDefault = useSyncExternalStore(
    subscribeGlobalDisplayMode,
    getGlobalDisplayModeSnapshot,
    getGlobalDisplayModeSnapshot,
  );

  const sessionOverride = useMemo(
    () => (sessionId ? displayModeStore.getSession(sessionId) : null),
    [sessionId, storeVersion],
  );
  const messageOverride = useMemo(
    () => (messageId ? displayModeStore.getMessage(messageId) : null),
    [messageId, storeVersion],
  );

  const mode = useMemo(
    () => resolveDisplayMode({ messageOverride, sessionOverride, globalDefault }),
    [messageOverride, sessionOverride, globalDefault],
  );

  const setSessionMode = useCallback(
    (m: DisplayMode) => {
      if (sessionId) displayModeStore.setSession(sessionId, m);
    },
    [sessionId],
  );

  const clearSessionMode = useCallback(() => {
    if (sessionId) displayModeStore.clearSession(sessionId);
  }, [sessionId]);

  const setMessageMode = useCallback(
    (m: DisplayMode) => {
      if (messageId) displayModeStore.setMessage(messageId, m);
    },
    [messageId],
  );

  const clearMessageMode = useCallback(() => {
    if (messageId) displayModeStore.clearMessage(messageId);
  }, [messageId]);

  return { mode, setSessionMode, clearSessionMode, setMessageMode, clearMessageMode };
}
