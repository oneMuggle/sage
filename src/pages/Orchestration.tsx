import { useEffect } from 'react';

import { useLaneBoardStore } from '../entities/orchestration/laneBoardStore';
import { useChatStreamStore } from '../features/send-message/chatStreamStore';
import { subscribeOrchEvents } from '../shared/api/orchEventStream';
import { LaneBoard } from '../widgets/orchestration/LaneBoard';

/** 同时订阅的活动 run 数上限（防订阅风暴）。 */
const MAX_ACTIVE_RUN_SUBSCRIPTIONS = 5;

export function Orchestration() {
  // live-events P2 (2026-09-07): LaneBoard 事件化 —— 订阅活动 run 的
  // canonical 事件流（task.* → lane 卡片投影,applyCanonicalEvent）,
  // 替代纯 REST 快照的"打开页面即陈旧"。活动 runId 从 chatStreamStore
  // 的会话槽位扫描（聊天中的编排 run 才有实时事件,历史 lane 静态快照
  // 兜底）。单 run 订阅失败不影响其余;卸载经 AbortSignal 取消订阅。
  useEffect(() => {
    const controller = new AbortController();
    const subscribed = new Set<string>();
    const knownRuns = new Set<string>();

    const reconcile = () => {
      const { sessions } = useChatStreamStore.getState();
      for (const slots of Object.values(sessions)) {
        const rid = slots.taskBoard?.runId;
        if (rid) knownRuns.add(rid);
      }
      for (const rid of knownRuns) {
        if (subscribed.has(rid) || controller.signal.aborted) continue;
        subscribed.add(rid);
        if (subscribed.size > MAX_ACTIVE_RUN_SUBSCRIPTIONS) continue;
        void (async () => {
          try {
            const stream = subscribeOrchEvents({
              runId: rid,
              signal: controller.signal,
            });
            for await (const event of stream) {
              if (event.event_type.startsWith('task.')) {
                useLaneBoardStore.getState().applyCanonicalEvent(event);
              }
            }
          } catch {
            // 单个 run 订阅失败不影响其余（降级静态快照）
          }
        })();
      }
    };

    reconcile();
    const unsubscribeStore = useChatStreamStore.subscribe(reconcile);
    return () => {
      controller.abort();
      unsubscribeStore();
    };
  }, []);

  return (
    <div className="flex-1 overflow-auto">
      <div className="max-w-7xl mx-auto px-6 py-6">
        <h1 className="text-2xl font-semibold mb-6">Orchestration Board</h1>
        <LaneBoard />
      </div>
    </div>
  );
}
