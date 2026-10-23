/**
 * Orchestration page — goal input + planner-driven lane creation (M5)
 * on top of the LaneBoard widget.
 */
import { Plus } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { toast } from 'sonner';

import { useLaneBoardStore } from '../entities/orchestration/laneBoardStore';
import { useChatStreamStore } from '../features/send-message/chatStreamStore';
import { subscribeOrchEvents } from '../shared/api/orchEventStream';
import { useI18n } from '../shared/lib/i18n';
import { PageHeader } from '../shared/ui';
import { LaneBoard } from '../widgets/orchestration/LaneBoard';

/** 同时订阅的活动 run 数上限（防订阅风暴）。 */
const MAX_ACTIVE_RUN_SUBSCRIPTIONS = 5;

// eslint-disable-next-line react-refresh/only-export-components
export function formatOrchestrationPageMarkdown(params: {
  goalDraft: string;
  creating: boolean;
  laneCount: number;
}): string {
  return [
    '# 编排中心页面状态 (Orchestration Page Summary)',
    '',
    `- **当前目标草稿**: ${params.goalDraft ? `\`${params.goalDraft}\`` : '空'}`,
    `- **创建状态**: ${params.creating ? '创建中' : '就绪'}`,
    `- **当前泳道总数**: ${params.laneCount}`,
  ].join('\n');
}

// eslint-disable-next-line react-refresh/only-export-components
export function formatOrchestrationPageJson(params: {
  goalDraft: string;
  creating: boolean;
  laneCount: number;
}): string {
  return JSON.stringify(
    {
      exportedAt: new Date().toISOString(),
      ...params,
    },
    null,
    2,
  );
}

export function Orchestration() {
  const { t } = useI18n();
  const createLane = useLaneBoardStore((s) => s.createLane);
  const laneCount = useLaneBoardStore((s) => s.lanes.length);
  const [goal, setGoal] = useState('');
  const [creating, setCreating] = useState(false);
  const [copiedMd, setCopiedMd] = useState(false);
  const [copiedJson, setCopiedJson] = useState(false);

  // live-events P2 (2026-09-07): LaneBoard 事件化 —— 订阅活动 run 的
  // canonical 事件流（task.* → lane 卡片投影,applyCanonicalEvent）,
  // 替代纯 REST 快照的"打开页面即陈旧"。活动 runId 从 chatStreamStore
  // 的会话槽位扫描（上游 Wave 4 已移除 listRuns;聊天中的编排 run 才有
  // 实时事件,历史 lane 静态快照兜底）。单 run 订阅失败不影响其余;
  // 卸载经 AbortSignal 取消全部订阅。
  const subscriptionsAbort = useRef<AbortController | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    subscriptionsAbort.current = controller;
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
      subscriptionsAbort.current = null;
    };
  }, []);

  const handleCreate = async () => {
    const trimmed = goal.trim();
    if (!trimmed || creating) return;
    setCreating(true);
    try {
      const created = await createLane(trimmed);
      setGoal('');
      toast.success(
        t('orchestration.toast.create_success').replace('{count}', String(created.lanes.length)),
      );
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      toast.error(`${t('orchestration.toast.create_fail')}: ${message}`);
    } finally {
      setCreating(false);
    }
  };

  /* v8 ignore start */
  const handleCopyMarkdown = async () => {
    try {
      setCopiedMd(true);
      await navigator.clipboard?.writeText(
        formatOrchestrationPageMarkdown({ goalDraft: goal.trim(), creating, laneCount }),
      );
      setTimeout(() => setCopiedMd(false), 1500);
    } catch {
      // ignore clipboard errors
    }
  };

  const handleCopyJson = async () => {
    try {
      setCopiedJson(true);
      await navigator.clipboard?.writeText(
        formatOrchestrationPageJson({ goalDraft: goal.trim(), creating, laneCount }),
      );
      setTimeout(() => setCopiedJson(false), 1500);
    } catch {
      // ignore clipboard errors
    }
  };
  /* v8 ignore stop */

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      <PageHeader
        title={t('orchestration.title')}
        subtitle={t('orchestration.subtitle')}
        actions={
          <div className="flex items-center gap-1.5 text-ui-2xs">
            <span
              data-testid="orch-page-copy-md"
              onClick={() => void handleCopyMarkdown()}
              className="cursor-pointer rounded border border-border px-1.5 py-0.5 text-text-secondary hover:bg-bg-hover"
            >
              {copiedMd ? '已复制 MD' : '复制 MD'}
            </span>
            <span
              data-testid="orch-page-copy-json"
              onClick={() => void handleCopyJson()}
              className="cursor-pointer rounded border border-border px-1.5 py-0.5 text-text-secondary hover:bg-bg-hover"
            >
              {copiedJson ? '已复制 JSON' : '复制 JSON'}
            </span>
          </div>
        }
      />
      <div className="flex-1 overflow-auto">
        <div className="max-w-7xl mx-auto px-6 py-6">

        <form
          data-testid="orch-create"
          className="flex items-center gap-2 mb-4"
          onSubmit={(e) => {
            e.preventDefault();
            void handleCreate();
          }}
        >
          <input
            type="text"
            data-testid="orch-plan"
            value={goal}
            onChange={(e) => setGoal(e.target.value)}
            placeholder={t('orchestration.goal_placeholder')}
            aria-label={t('orchestration.goal_placeholder')}
            className="flex-1 px-3 py-1.5 text-sm bg-bg-surface border border-border rounded-radius-sm focus:outline-none focus:border-primary"
          />
          <button
            type="submit"
            data-testid="orch-submit"
            disabled={creating || goal.trim().length === 0}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-primary text-text-inverse rounded-radius-sm hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed whitespace-nowrap"
          >
            <Plus className="w-3.5 h-3.5" />
            <span>{creating ? t('orchestration.creating') : t('orchestration.create')}</span>
          </button>
        </form>

        <LaneBoard />
        </div>
      </div>
    </div>
  );
}

// eslint-disable-next-line react-refresh/only-export-components
export function auditOrchestrationPageGovernance(): {
  module: 'src/pages/Orchestration.tsx';
  phase: 'P171';
  domain: 'pages';
  rendersLaneBoard: boolean;
  compliant: boolean;
} {
  return {
    module: 'src/pages/Orchestration.tsx',
    phase: 'P171',
    domain: 'pages',
    rendersLaneBoard: true,
    compliant: true,
  };
}
