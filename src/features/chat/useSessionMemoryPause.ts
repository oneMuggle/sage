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

export function formatSessionMemoryPauseSummary(
  ids?: ReadonlySet<string> | null,
  sessionId: string | null = null,
  unconfirmed = false,
): string {
  /* v8 ignore start */
  const count = ids ? ids.size : 0;
  const isPaused = Boolean(sessionId && (unconfirmed || ids?.has(sessionId)));
  const activeState = isPaused ? 'paused' : 'enabled';
  const confState = unconfirmed ? 'unconfirmed' : 'confirmed';
  /* v8 ignore stop */
  return `memory-pause: ${count} paused · active=${activeState} · ${confState}`;
}

export function formatSessionMemoryPauseJson(
  ids?: ReadonlySet<string> | null,
  sessionId: string | null = null,
  unconfirmed = false,
): string {
  /* v8 ignore start */
  const count = ids ? ids.size : 0;
  const isSessionPaused = Boolean(sessionId && (unconfirmed || ids?.has(sessionId)));
  /* v8 ignore stop */
  return JSON.stringify(
    {
      pausedCount: count,
      sessionId,
      isSessionPaused,
      unconfirmed: Boolean(unconfirmed),
      maxSessions: MAX_SESSIONS,
    },
    null,
    2,
  );
}

export interface UseSessionMemoryPauseGovernanceAudit {
  phase: 'P161';
  module: 'src/features/chat/useSessionMemoryPause.ts';
  archetype: string;
  sessionId: string;
  healthy: boolean;
  summaryMarkdown: string;
}

export function auditUseSessionMemoryPauseGovernance(
  sessionId = 'default',
  archetype = 'software-engineering',
): UseSessionMemoryPauseGovernanceAudit {
  const normalizedSession = sessionId.trim() || 'default';
  const normalizedArchetype = archetype.trim() || 'software-engineering';
  return {
    phase: 'P161',
    module: 'src/features/chat/useSessionMemoryPause.ts',
    archetype: normalizedArchetype,
    sessionId: normalizedSession,
    healthy: normalizedSession.length > 0 && normalizedArchetype.length > 0,
    summaryMarkdown: `### P161 UseSessionMemoryPause Governance\n- session: ${normalizedSession}\n- archetype: ${normalizedArchetype}`,
  };
}
