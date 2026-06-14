import { useCallback } from 'react';

import { useStore } from '../shared/lib/store';

export function useSessions() {
  const {
    sessions,
    currentSessionId,
    loadSessions,
    setCurrentSessionId,
    createSession,
    deleteSession,
  } = useStore();

  const handleCreateSession = useCallback(async () => {
    const id = await createSession();
    return id;
  }, [createSession]);

  const handleDeleteSession = useCallback(
    async (id: string) => {
      await deleteSession(id);
    },
    [deleteSession],
  );

  const handleSelectSession = useCallback(
    (id: string) => {
      setCurrentSessionId(id);
    },
    [setCurrentSessionId],
  );

  return {
    sessions,
    currentSessionId,
    loadSessions,
    createSession: handleCreateSession,
    deleteSession: handleDeleteSession,
    selectSession: handleSelectSession,
  };
}
