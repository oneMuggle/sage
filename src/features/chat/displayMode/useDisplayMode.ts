import { useCallback, useMemo } from 'react';

import { useConfirmedPreference } from '../../manage-settings/useConfirmedPreference';

import { displayModeStore } from './displayModeStore';
import { resolveDisplayMode, type DisplayMode } from './resolveDisplayMode';
import { DEFAULT_DISPLAY_MODE, isValidDisplayMode } from './types';

export function useDisplayMode(sessionId: string | null, messageId: string | null) {
  const globalPref = useConfirmedPreference<DisplayMode>({
    key: 'chat_display_mode',
    initial: DEFAULT_DISPLAY_MODE,
    parse: (value) => (value && isValidDisplayMode(value) ? value : DEFAULT_DISPLAY_MODE),
    serialize: (value) => value,
    category: 'ui',
  });

  const sessionOverride = sessionId ? displayModeStore.getSession(sessionId) : null;
  const messageOverride = messageId ? displayModeStore.getMessage(messageId) : null;

  const mode = useMemo(
    () =>
      resolveDisplayMode({
        messageOverride,
        sessionOverride,
        globalDefault: globalPref.value,
      }),
    [messageOverride, sessionOverride, globalPref.value],
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

  return {
    mode,
    setSessionMode,
    clearSessionMode,
    setMessageMode,
    clearMessageMode,
  };
}
