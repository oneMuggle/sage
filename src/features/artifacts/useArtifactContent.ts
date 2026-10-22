// src/features/artifacts/useArtifactContent.ts
import { useState, useEffect, useCallback } from 'react';

import { readArtifactContent, type ArtifactContent } from './artifactApi';

export function useArtifactContent(sessionId: string, artifactId: string | null) {
  const [content, setContent] = useState<ArtifactContent | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!artifactId) {
      setContent(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    // readArtifactContent REJECTS on a non-2xx response (Task 6 contract), so
    // a plain .then/.finally chain would leave an UNHANDLED rejection. The
    // .catch converts the failure into an error-shaped content object so the
    // viewer's existing error state (content.ok === false) can render it.
    readArtifactContent(sessionId, artifactId)
      .then((c) => {
        if (!cancelled) setContent(c);
      })
      .catch((e: unknown) => {
        if (!cancelled) {
          setContent({ ok: false, error: e instanceof Error ? e.message : String(e) });
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [sessionId, artifactId]);

  const refresh = useCallback(async () => {
    if (!artifactId) return;
    try {
      const c = await readArtifactContent(sessionId, artifactId);
      setContent(c);
    } catch (e: unknown) {
      setContent({ ok: false, error: e instanceof Error ? e.message : String(e) });
    }
  }, [sessionId, artifactId]);

  return { content, loading, refresh };
}

export function formatArtifactContentStateSummary(
  content: ArtifactContent | null,
  loading: boolean,
): string {
  if (loading) return 'loading';
  if (!content) return 'empty';
  if (!content.ok) return `error · ${content.error ?? 'unknown'}`;
  return `ok · ${content.kind ?? 'unknown'} · ${(content.content ?? '').length} chars`;
}

export function formatArtifactContentStateJson(
  content: ArtifactContent | null,
  loading: boolean,
): string {
  return JSON.stringify(
    {
      loading,
      hasContent: content !== null,
      ok: content?.ok ?? null,
      kind: content?.kind ?? null,
      contentLength: content?.content?.length ?? 0,
      truncated: Boolean(content?.truncated),
      error: content?.error ?? null,
    },
    null,
    2,
  );
}

export function auditUseArtifactContentGovernance(
  state: {
    sessionId?: string;
    hasError?: boolean;
  } = {},
): {
  module: 'src/features/artifacts/useArtifactContent.ts';
  phase: 'P158';
  sessionId: string;
  hasError: boolean;
  healthy: boolean;
} {
  const sessionId =
    typeof state.sessionId === 'string' && state.sessionId.trim().length > 0
      ? state.sessionId.trim()
      : 'default';
  const hasError = state.hasError === true;
  return {
    module: 'src/features/artifacts/useArtifactContent.ts',
    phase: 'P158',
    sessionId,
    hasError,
    healthy: sessionId.length > 0 && !hasError,
  };
}
