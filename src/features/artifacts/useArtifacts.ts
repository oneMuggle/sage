// src/features/artifacts/useArtifacts.ts
import { useState, useEffect, useCallback } from 'react';
import { listArtifacts, type Artifact } from './artifactApi';

export function useArtifacts(sessionId: string | null) {
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    if (!sessionId) return;
    setLoading(true);
    try {
      setArtifacts(await listArtifacts(sessionId));
    } catch {
      // keep previous artifacts on transient failure; don't crash the caller
    } finally {
      setLoading(false);
    }
  }, [sessionId]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return { artifacts, loading, refresh };
}
