import { useEffect, useMemo, useRef, useState } from 'react';
import { toast } from 'sonner';

import { useI18n } from '../../shared/lib/i18n';
import { productMessages } from '../../shared/lib/productMessages';

const KEY = 'sage:paused-memory-sessions:v1';
const LEGACY_KEY = 'sage:temp-chat-sessions';
const MAX_SESSIONS = 2048;

function readPreference(): { ids: ReadonlySet<string>; unconfirmed: boolean } {
  if (typeof window === 'undefined') return { ids: new Set(), unconfirmed: false };
  try {
    const stored = localStorage.getItem(KEY);
    const raw = stored ?? sessionStorage.getItem(LEGACY_KEY);
    if (raw === null) return { ids: new Set(), unconfirmed: false };
    const list: unknown = JSON.parse(raw);
    if (
      !Array.isArray(list) ||
      list.length > MAX_SESSIONS ||
      list.some((id) => typeof id !== 'string' || !id || id.length > 256)
    ) {
      throw new Error('Invalid memory preference');
    }
    return { ids: new Set(list as string[]), unconfirmed: false };
  } catch {
    return { ids: new Set(), unconfirmed: true };
  }
}

/** Device-local per-session pause; this is not an ephemeral-history or offline mode. */
export function useSessionMemoryPause(sessionId: string | null) {
  const { locale } = useI18n();
  const [initial] = useState(readPreference);
  const [ids, setIds] = useState<ReadonlySet<string>>(initial.ids);
  const [unconfirmed, setUnconfirmed] = useState(initial.unconfirmed);
  const warned = useRef(false);
  const effective = useMemo(
    () => (unconfirmed && sessionId ? new Set([...ids, sessionId]) : ids),
    [ids, sessionId, unconfirmed],
  );

  useEffect(() => {
    if (unconfirmed) {
      if (!warned.current && sessionId) {
        warned.current = true;
        toast.warning(productMessages(locale).memoryUnconfirmed);
      }
      return;
    }
    try {
      if (ids.size > MAX_SESSIONS) throw new Error('Memory preference limit exceeded');
      localStorage.setItem(KEY, JSON.stringify([...ids]));
      // Once the durable key exists it is authoritative, including an empty list.
      try {
        sessionStorage.removeItem(LEGACY_KEY);
      } catch {
        /* durable write succeeded */
      }
    } catch {
      setUnconfirmed(true);
    }
  }, [ids, unconfirmed, sessionId, locale]);

  return [effective, setIds, unconfirmed] as const;
}
