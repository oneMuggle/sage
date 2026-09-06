// src/features/artifacts/useArtifacts.ts
import { useState, useEffect, useCallback } from 'react';

import { listArtifacts, type Artifact } from './artifactApi';
import { useArtifactEventsStore } from './artifactEventsStore';

export function useArtifacts(sessionId: string | null) {
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [loading, setLoading] = useState(false);

  // S7 (2026-09-06): 事件驱动刷新 —— 流式过程中工具落库产物会推
  // `artifact_created` 事件（经 useChat → artifactEventsStore 计数），
  // 计数变化即重新拉取列表；不再依赖手动刷新。
  const artifactEventCount = useArtifactEventsStore((s) =>
    sessionId != null ? (s.counts[sessionId] ?? 0) : 0,
  );

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

  useEffect(() => {
    // 计数从 0→N（流式产出新产物）时刷新；0 时只是切会话，由上面的
    // refresh effect 负责。跳过首次渲染的冗余请求。
    if (artifactEventCount > 0) {
      refresh();
    }
  }, [artifactEventCount, refresh]);

  return { artifacts, loading, refresh };
}
