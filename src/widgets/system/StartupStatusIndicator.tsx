/**
 * Progressive readiness 状态条。
 *
 * - warming：显示「正在加载后台服务（done/total）」+ 细进度条；
 * - L3 + 无降级：自动隐藏（后台全部就绪，无需打扰）；
 * - L3 + 有降级：常驻「N 项功能降级」提示，悬停可看逐模块状态。
 *
 * 数据来自主进程轮询的 `/health/ready` 快照（事件 + 初始快照双通道）。
 */
import { useEffect, useState } from 'react';

import {
  fetchStartupStatusSnapshot,
  subscribeStartupStatus,
  type StartupStatusSnapshot,
} from '../../shared/lib/startupStatus';

const MODULE_LABELS: Record<string, string> = {
  database: '数据库',
  memory: '记忆',
  sessions: '会话',
  chat_service: '对话服务',
  llm: 'LLM 端点',
  mcp: 'MCP 服务',
  scheduler: '调度器',
  todo: '待办',
  review_queue: '审阅队列',
  wake_scheduler: '唤醒调度',
  gateways: '消息网关',
  design_studio: '设计工作台',
  multi_agent: '多智能体',
  arena: 'Arena',
  storage: '磁盘存储',
};

const STATE_LABELS: Record<string, string> = {
  pending: '等待中',
  warming: '加载中',
  ready: '就绪',
  degraded: '降级',
  failed: '失败',
};

export function moduleLabel(name: string): string {
  return MODULE_LABELS[name] ?? name;
}

export function describeModules(snapshot: StartupStatusSnapshot): string {
  return Object.entries(snapshot.modules)
    .map(([name, entry]) => `${moduleLabel(name)}：${STATE_LABELS[entry.state] ?? entry.state}`)
    .join('\n');
}

export function StartupStatusIndicator() {
  const [snapshot, setSnapshot] = useState<StartupStatusSnapshot | null>(null);

  useEffect(() => {
    let cancelled = false;
    let unlisten: (() => void) | undefined;
    void (async () => {
      // 快照兜底已发生的事件，订阅接住后续迁移；两者之间即使漏一拍，
      // 下一轮轮询（1s）也会补上。
      const initial = await fetchStartupStatusSnapshot();
      if (!cancelled && initial) setSnapshot(initial);
      const off = await subscribeStartupStatus((next) => {
        if (!cancelled) setSnapshot(next);
      });
      if (cancelled) off();
      else unlisten = off;
    })();
    return () => {
      cancelled = true;
      unlisten?.();
    };
  }, []);

  if (!snapshot) return null;

  const degraded = Object.entries(snapshot.modules).filter(
    ([, entry]) => entry.state === 'degraded' || entry.state === 'failed',
  );
  if (snapshot.phase === 'L3' && degraded.length === 0) return null;

  if (snapshot.phase === 'L3') {
    return (
      <div
        role="status"
        data-testid="startup-status-indicator"
        data-state="degraded"
        title={describeModules(snapshot)}
        className="px-3 py-1.5 text-ui-2xs text-warning bg-bg-hover border-b border-border flex items-center gap-2"
      >
        <span>
          {degraded.length} 项功能降级：
          {degraded.map(([name]) => moduleLabel(name)).join('、')}
        </span>
      </div>
    );
  }

  const total = Math.max(snapshot.warmup.total, 1);
  const percent = Math.min(100, Math.round((snapshot.warmup.done / total) * 100));
  return (
    <div
      role="status"
      data-testid="startup-status-indicator"
      data-state="warming"
      title={describeModules(snapshot)}
      className="px-3 py-1.5 text-ui-2xs text-muted bg-bg-hover border-b border-border flex items-center gap-2"
    >
      <span className="shrink-0">
        正在加载后台服务（{snapshot.warmup.done}/{snapshot.warmup.total}）
      </span>
      <div className="h-0.5 flex-1 rounded bg-border overflow-hidden">
        <div className="h-full bg-primary transition-all" style={{ width: `${percent}%` }} />
      </div>
    </div>
  );
}
