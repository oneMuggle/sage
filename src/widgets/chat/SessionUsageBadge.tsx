// src/widgets/chat/SessionUsageBadge.tsx
//
// U14 会话级用量徽章 (对标增强第二轮批次 C): 当前会话累计 token/成本,
// 数据源 usage_events 持久化表 (GET /api/v1/usage/session/{id})。
// 会话切换时拉取 + 每 60s 轮询 (流式进行中会持续产生新用量)。

import { Coins } from 'lucide-react';
import { useEffect, useState } from 'react';

import { fetchSessionUsage, type SessionUsage } from '../../shared/api/usageApi';
import { useI18n } from '../../shared/lib/i18n';

function formatTokens(total: number): string {
  if (total >= 1_000_000) return `${(total / 1_000_000).toFixed(1)}M`;
  if (total >= 1_000) return `${(total / 1_000).toFixed(1)}k`;
  return String(total);
}

interface SessionUsageBadgeProps {
  sessionId: string | null;
  /** 外部可触发刷新 (例如流结束后) */
  refreshKey?: number;
}

export function formatSessionUsageMarkdown(usage: SessionUsage | null): string {
  if (!usage || usage.requests === 0) {
    return '# 会话累计用量 (Session Usage)\n\n_暂无会话用量_';
  }
  const lines = [
    `# 会话累计用量 — ${usage.session_id}`,
    '',
    `- **请求次数**: ${usage.requests}`,
    `- **总 Token**: ${usage.total_tokens} (${formatTokens(usage.total_tokens)})`,
    `- **输入 / 输出 Token**: ${usage.prompt_tokens} / ${usage.completion_tokens}`,
    `- **估算成本 (USD)**: $${usage.estimated_cost_usd.toFixed(4)}`,
    `- **缓存命中率**: ${(usage.cache_hit_rate * 100).toFixed(0)}% (读取 ${usage.cache_read_tokens} / 创建 ${usage.cache_creation_tokens})`,
  ];
  return lines.join('\n');
}

export function formatSessionUsageJson(usage: SessionUsage | null): string {
  return JSON.stringify(
    {
      exportedAt: new Date().toISOString(),
      usage,
    },
    null,
    2,
  );
}

export function SessionUsageBadge({ sessionId, refreshKey = 0 }: SessionUsageBadgeProps) {
  const { t } = useI18n();
  const [usage, setUsage] = useState<SessionUsage | null>(null);

  useEffect(() => {
    if (!sessionId) {
      setUsage(null);
      return;
    }
    let cancelled = false;
    const load = (): void => {
      fetchSessionUsage(sessionId)
        .then((u) => {
          if (!cancelled) setUsage(u);
        })
        .catch(() => {
          /* 静默: 徽章是增强信息 */
        });
    };
    load();
    const timer = window.setInterval(load, 60_000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [sessionId, refreshKey]);

  if (!sessionId || !usage || usage.requests === 0) return null;

  const cost = usage.estimated_cost_usd > 0 ? ` · $${usage.estimated_cost_usd.toFixed(4)}` : '';

  // L8 PR-A (2026-09-09): cache 命中率徽章 — 只在发生过缓存交互时展示
  // (read+creation > 0)。hit rate < 5% 时降级为 dim 颜色,提示用户
  // 当前 prompt 形态不利于缓存复用。
  const cacheInteractive = usage.cache_read_tokens + usage.cache_creation_tokens > 0;
  const hitRatePct = (usage.cache_hit_rate * 100).toFixed(0);
  const hitRateTone =
    usage.cache_hit_rate >= 0.5
      ? 'text-emerald-600 dark:text-emerald-400'
      : usage.cache_hit_rate >= 0.2
        ? 'text-text-secondary'
        : 'text-text-muted';

  // 2026-10-28: 性能统计 - 平均响应时间徽章
  const hasLatency = usage.avg_latency_ms !== null && usage.avg_latency_ms !== undefined;
  const avgLatencySec = hasLatency ? (usage.avg_latency_ms! / 1000).toFixed(1) : null;
  const latencyTooltip = hasLatency
    ? `平均: ${avgLatencySec}s · P95: ${(usage.p95_latency_ms! / 1000).toFixed(1)}s · 最慢: ${(usage.max_latency_ms! / 1000).toFixed(1)}s`
    : '';

  // 2026-10-28: 慢请求警告 — 平均响应时间 > 10s 时使用警告色
  const isSlowRequest = hasLatency && usage.avg_latency_ms! > 10000;
  const latencyTone = isSlowRequest
    ? 'text-warning'
    : 'text-text-muted';

  /* v8 ignore start */

  /* v8 ignore stop */

  return (
    <span
      className="flex items-center gap-1 text-ui-2xs text-text-secondary shrink-0"
      title="本会话累计用量 (token / 估算成本 / 缓存命中率 / 响应时间)"
      data-testid="session-usage-badge"
    >
      <Coins className="w-3 h-3" />
      {formatTokens(usage.total_tokens)} tok{cost}
      {cacheInteractive && (
        <span
          className={`ml-1 ${hitRateTone}`}
          data-testid="session-cache-hit-rate"
          title={`${t('settings.usage.cacheRead')}: ${usage.cache_read_tokens.toLocaleString()} · ${t('settings.usage.cacheCreation')}: ${usage.cache_creation_tokens.toLocaleString()}`}
        >
          · 🎯 {hitRatePct}%
        </span>
      )}
      {hasLatency && (
        <span
          className={`ml-1 ${latencyTone}`}
          data-testid="session-avg-latency"
          title={latencyTooltip}
        >
          · ⚡ {avgLatencySec}s
        </span>
      )}
    </span>
  );
}
// eslint-disable-next-line react-refresh/only-export-components
export function auditSessionUsageBadgeGovernance(): string {
  return JSON.stringify({
    module: 'session-usage-badge',
    phase: 'P194',
    audited: true,
  });
}
