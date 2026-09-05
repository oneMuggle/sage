import { useCallback, useEffect, useState } from 'react';

const DRAFTS_KEY = 'sage-drafts';

interface DraftStore {
  [sessionId: string]: string;
}

/**
 * Per-session draft persistence (U13 from OpenWorker).
 *
 * Stores each session's draft independently so switching sessions
 * doesn't lose half-typed messages.
 *
 * @param sessionId - Current session ID (null = no persistence)
 * @returns [draft, setDraft] - Draft value and setter
 */
export function useSessionDraft(sessionId: string | null): [string, (value: string) => void] {
  // Load draft for current session on mount or session change
  const [draft, setDraftState] = useState<string>(() => {
    if (!sessionId) return '';
    try {
      const store = JSON.parse(localStorage.getItem(DRAFTS_KEY) ?? '{}') as DraftStore;
      return store[sessionId] ?? '';
    } catch {
      return '';
    }
  });

  // Update draft and persist to localStorage
  const setDraft = useCallback(
    (value: string) => {
      setDraftState(value);
      if (sessionId) {
        try {
          const store = JSON.parse(localStorage.getItem(DRAFTS_KEY) ?? '{}') as DraftStore;
          store[sessionId] = value;
          localStorage.setItem(DRAFTS_KEY, JSON.stringify(store));
        } catch {
          // Silently fail - privacy mode or quota exceeded
        }
      }
    },
    [sessionId],
  );

  // Load draft when sessionId changes
  useEffect(() => {
    if (sessionId) {
      try {
        const store = JSON.parse(localStorage.getItem(DRAFTS_KEY) ?? '{}') as DraftStore;
        setDraftState(store[sessionId] ?? '');
      } catch {
        setDraftState('');
      }
    } else {
      setDraftState('');
    }
  }, [sessionId]);

  return [draft, setDraft];
}
