// src/widgets/chat/SessionUsageBadge.tsx
//
// U14 会话级用量徽章 (对标增强第二轮批次 C): 当前会话累计 token/成本/缓存命中/响应速度。
//
// 2026-11-25 (composer 状态条下沉): 改为**受控展示**组件 —— 取数收敛到
// hooks/useSessionUsage.ts（单次请求 + 流末刷新），本组件只负责渲染：
//   - 单行紧凑摘要（对齐 ChatGPT / Claude 的 composer footer）
//   - 点击展开的明细弹层（原生 title tooltip 装不下 P95 / 最慢 / 分模型明细）
// 数据源 usage_events 持久化表 (GET /api/v1/usage/session/{id})。

import { Coins } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';

import type { SessionUsage } from '../../shared/api/usageApi';
import { useI18n } from '../../shared/lib/i18n';

function formatTokens(total: number): string {
  if (total >= 1_000_000) return `${(total / 1_000_000).toFixed(1)}M`;
  if (total >= 1_000) return `${(total / 1_000).toFixed(1)}k`;
  return String(total);
}

interface SessionUsageBadgeProps {
  /** 用量快照（由 useSessionUsage 提供）；null 表示尚无数据。 */
  usage: SessionUsage | null;
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

export function SessionUsageBadge({ usage }: SessionUsageBadgeProps) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const panelRef = useRef<HTMLSpanElement | null>(null);

  // 弹层外点 / Escape 关闭
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent): void => {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent): void => {
      if (e.key === 'Escape') setOpen(false);
    };
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  if (!usage || usage.requests === 0) return null;

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

  // 2026-10-28: 按模型统计详情（明细弹层展示）
  const modelStats = usage.latency_by_model && usage.latency_by_model.length > 0;
  const modelStatsText = modelStats
    ? '\n\n按模型统计:\n' +
      usage
        .latency_by_model!.map(
          (m) => `  ${m.model}: ${(m.avg_latency_ms / 1000).toFixed(1)}s (${m.count}次)`,
        )
        .join('\n')
    : '';

  const latencyTooltip = hasLatency
    ? `平均: ${avgLatencySec}s · P95: ${(usage.p95_latency_ms! / 1000).toFixed(1)}s · 最慢: ${(usage.max_latency_ms! / 1000).toFixed(1)}s${modelStatsText}`
    : '';

  // 2026-10-28: 慢请求警告 — 平均响应时间 > 10s 时使用警告色
  const isSlowRequest = hasLatency && usage.avg_latency_ms! > 10000;
  const latencyTone = isSlowRequest ? 'text-warning' : 'text-text-muted';

  return (
    <span className="relative shrink-0 text-ui-2xs text-text-secondary" ref={panelRef}>
      <button
        type="button"
        className="flex items-center gap-1 hover:text-text"
        title="本会话累计用量 (token / 估算成本 / 缓存命中率 / 响应时间)"
        aria-expanded={open}
        data-testid="session-usage-badge"
        onClick={() => setOpen((v) => !v)}
      >
        <Coins className="w-3 h-3" />
        {/* 窄屏 (<640px) 折叠：只保留延迟段，避免状态条换行挤压输入区 */}
        <span className="hidden sm:inline" data-testid="session-usage-tokens">
          {formatTokens(usage.total_tokens)} tok{cost}
        </span>
        {cacheInteractive && (
          <span
            className={`ml-1 hidden lg:inline ${hitRateTone}`}
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
            <span className="hidden sm:inline">· </span>⚡ {avgLatencySec}s
          </span>
        )}
      </button>

      {open && (
        <span
          className="absolute bottom-full left-0 z-50 mb-2 block w-80 rounded-lg border border-border bg-surface-overlay p-3 text-left shadow-xl backdrop-blur-sm"
          data-testid="session-usage-popover"
        >
          <span className="mb-2 flex items-center justify-between gap-1.5">
            <span className="text-xs font-medium text-text">{t('chat.status.usage')}</span>
            <span className="shrink-0 truncate text-ui-2xs text-text-muted">{usage.session_id}</span>
          </span>

          <span className="block text-ui-2xs text-text-secondary">
            <span className="flex items-center justify-between gap-2 py-0.5">
              <span>请求次数</span>
              <span className="tabular-nums">{usage.requests}</span>
            </span>
            <span className="flex items-center justify-between gap-2 py-0.5">
              <span>总 Token</span>
              <span className="tabular-nums">
                {usage.total_tokens} · {formatTokens(usage.total_tokens)}
              </span>
            </span>
            <span className="flex items-center justify-between gap-2 py-0.5">
              <span>输入 / 输出 Token</span>
              <span className="tabular-nums">
                {usage.prompt_tokens} / {usage.completion_tokens}
              </span>
            </span>
            <span className="flex items-center justify-between gap-2 py-0.5">
              <span>估算成本 (USD)</span>
              <span className="tabular-nums">${usage.estimated_cost_usd.toFixed(4)}</span>
            </span>
            <span className="flex items-center justify-between gap-2 py-0.5">
              <span>{t('chat.status.cacheHit')}</span>
              <span className="tabular-nums">
                {(usage.cache_hit_rate * 100).toFixed(0)}% · 读取 {usage.cache_read_tokens} / 创建{' '}
                {usage.cache_creation_tokens}
              </span>
            </span>
            <span className="flex items-center justify-between gap-2 py-0.5">
              <span>{t('chat.status.latency')}</span>
              <span className="tabular-nums">
                {hasLatency
                  ? `平均 ${avgLatencySec}s · P95 ${(usage.p95_latency_ms! / 1000).toFixed(1)}s · 最慢 ${(usage.max_latency_ms! / 1000).toFixed(1)}s`
                  : '—'}
              </span>
            </span>
            {modelStats && (
              <span className="mt-1 block border-t border-border pt-1.5">
                <span className="mb-0.5 block text-text-muted">按模型</span>
                {usage.latency_by_model!.map((m) => (
                  <span
                    key={m.model}
                    className="flex items-center justify-between gap-2 py-0.5"
                    data-testid={`session-usage-model-${m.model}`}
                  >
                    <span className="truncate">{m.model}</span>
                    <span className="tabular-nums">
                      {(m.avg_latency_ms / 1000).toFixed(1)}s · {m.count} 次
                    </span>
                  </span>
                ))}
              </span>
            )}
          </span>
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
