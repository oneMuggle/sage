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

/**
 * 2026-09 修复: 删除会话时清理其草稿 —— 此前 sage-drafts 里的条目
 * 无限累积 (隐私残留 + 存储缓慢增长)。由 deleteSessionCascade 调用。
 */
export function clearSessionDraft(sessionId: string): void {
  try {
    const store = JSON.parse(localStorage.getItem(DRAFTS_KEY) ?? '{}') as DraftStore;
    if (sessionId in store) {
      delete store[sessionId];
      localStorage.setItem(DRAFTS_KEY, JSON.stringify(store));
    }
  } catch {
    // privacy mode or quota exceeded — same tolerance as writes
  }
}
