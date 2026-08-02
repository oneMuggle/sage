// src/features/artifacts/useArtifactContent.ts
import { useState, useEffect } from 'react';

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

  return { content, loading };
}
