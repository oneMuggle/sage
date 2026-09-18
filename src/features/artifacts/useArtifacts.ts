// src/features/artifacts/useArtifacts.ts
import { useCallback, useEffect } from 'react';

import type { Artifact } from './artifactApi';
import { useArtifactEventsStore } from './artifactEventsStore';
import { useArtifactListStore } from './artifactListStore';

/**
 * 产物列表 hook（right-panel R1 批次 A 起为 artifactListStore 的封装）。
 * 对外 API 不变：{ artifacts, loading, refresh }。多个组件（右侧面板 +
 * 消息流内联卡片）共用同一份按会话缓存，事件驱动刷新只发一次请求；
 * inflight 去重在 store 层完成。失败保留旧列表（与旧实现一致）。
 */
export function useArtifacts(sessionId: string | null): {
  artifacts: Artifact[];
  loading: boolean;
  refresh: () => Promise<void>;
} {
  const cached = useArtifactListStore((s) =>
    sessionId != null ? s.bySession[sessionId] : undefined,
  );
  const fetchArtifacts = useArtifactListStore((s) => s.fetch);

  // S7 (2026-09-06): 事件驱动刷新 —— 流式过程中工具落库产物会推
  // `artifact_created` 事件（经 useChat → artifactEventsStore 计数），
  // 计数变化即重新拉取列表；不再依赖手动刷新。
  const artifactEventCount = useArtifactEventsStore((s) =>
    sessionId != null ? (s.counts[sessionId] ?? 0) : 0,
  );

  const refresh = useCallback(async () => {
    if (!sessionId) return;
    await fetchArtifacts(sessionId);
  }, [sessionId, fetchArtifacts]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    // 计数从 0→N（流式产出新产物）时刷新；0 时只是切会话，由上面的
    // refresh effect 负责。跳过首次渲染的冗余请求。
    if (artifactEventCount > 0) {
      void refresh();
    }
  }, [artifactEventCount, refresh]);

  return {
    artifacts: cached ?? [],
    // 列表尚未拉到（缓存缺失且有会话）即视为加载中 —— 供列表骨架/文案用
    loading: sessionId != null && cached === undefined,
    refresh,
  };
}
