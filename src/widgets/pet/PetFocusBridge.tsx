/**
 * Report the session focused in the main window to the Electron main process.
 *
 * The pet overlay follows this focus unless a pet is pinned or urgent-first.
 * Debounced so rapid tab switches produce one IPC.
 */

import { useEffect } from 'react';

import { useStore } from '../../shared/lib/store';

const FOCUS_DEBOUNCE_MS = 150;

export function PetFocusBridge(): null {
  useEffect(() => {
    const pet = typeof window !== 'undefined' ? window.electronAPI?.pet : undefined;
    if (!pet) return undefined;

    let timer: ReturnType<typeof setTimeout> | null = null;
    let last: string | null | undefined;

    const report = (sessionId: string | null): void => {
      if (sessionId === last) return;
      last = sessionId;
      if (timer) clearTimeout(timer);
      timer = setTimeout(() => {
        timer = null;
        pet.reportFocusSession(sessionId);
      }, FOCUS_DEBOUNCE_MS);
    };

    report(useStore.getState().currentSessionId);
    const unsubscribe = useStore.subscribe((state) => {
      report(state.currentSessionId);
    });

    return () => {
      unsubscribe();
      if (timer) clearTimeout(timer);
    };
  }, []);

  return null;
}
