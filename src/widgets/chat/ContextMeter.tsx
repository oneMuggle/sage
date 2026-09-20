// src/widgets/chat/ContextMeter.tsx
//
// U17 上下文用量指示 (对标增强第四轮批次 B) + 分类明细弹层:
// 当前会话的模型上下文窗口占用率。数据源: GET /api/v1/usage/session/{id} 的
// last_prompt_tokens(上一轮请求 prompt = 当前上下文占用的最佳代理) +
// last_context_breakdown(该次请求 prompt 的分类构成, 后端估算并按实报校准) +
// last_model(经 catalog/用户设置解析出有效窗口)。
// 刷新时机: 流结束跳变(后台会话跑完也刷新) + 60s 兜底轮询 + 外部 refreshKey。

import { useEffect, useRef, useState } from 'react';

import {
  useChatStreamStore,
  selectSessionSlots,
} from '../../features/send-message/chatStreamStore';
import type { ContextBreakdown } from '../../shared/api/usageApi';
import { fetchSessionUsage, type SessionUsage } from '../../shared/api/usageApi';
import { resolvedContextWindow } from '../../shared/lib/modelWindows';

function formatTokens(total: number): string {
  if (total >= 1_000_000) return `${(total / 1_000_000).toFixed(1)}M`;
  if (total >= 1_000) return `${(total / 1_000).toFixed(1)}k`;
  return String(total);
}

/** 占用率 → 颜色档位: <70% 常态, 70-90% 注意, ≥90% 临近压缩/截断 */
function toneClass(pct: number): { bar: string; text: string } {
  if (pct >= 0.9) return { bar: 'bg-error', text: 'text-error' };
  if (pct >= 0.7) return { bar: 'bg-warning', text: 'text-warning' };
  return { bar: 'bg-accent', text: 'text-text-secondary' };
}

/** 明细类别的展示顺序 / 中文名 / 配色 (与后端 CATEGORY_ORDER 对齐) */
const CATEGORY_META: { key: string; label: string; color: string }[] = [
  { key: 'tools', label: '工具定义', color: 'bg-orange-500' },
  { key: 'system', label: '系统提示词', color: 'bg-sky-500' },
  { key: 'skills', label: '技能清单', color: 'bg-teal-500' },
  { key: 'dynamic_context', label: '动态上下文 (环境/记忆/附件)', color: 'bg-indigo-500' },
  { key: 'current_input', label: '当前输入', color: 'bg-pink-500' },
  { key: 'history_tool', label: '历史 · 工具结果', color: 'bg-amber-500' },
  { key: 'history_assistant', label: '历史 · 助手消息', color: 'bg-emerald-500' },
  { key: 'history_user', label: '历史 · 用户消息', color: 'bg-violet-500' },
];

interface ContextMeterProps {
  sessionId: string | null;
  /** 外部可触发刷新 (例如流结束后) */
  refreshKey?: number;
}

export function ContextMeter({ sessionId, refreshKey = 0 }: ContextMeterProps) {
  const [usage, setUsage] = useState<SessionUsage | null>(null);
  const [open, setOpen] = useState(false);
  const panelRef = useRef<HTMLSpanElement | null>(null);
  // 流结束跳变检测: 本会话 streaming.messageId 非空 → null 时刷新用量
  const streamingMessageId = useChatStreamStore(
    (s) => selectSessionSlots(s, sessionId).streaming?.messageId ?? null,
  );
  const prevStreamingIdRef = useRef<string | null>(null);

  const load = (sid: string | null): void => {
    if (!sid) {
      setUsage(null);
      return;
    }
    fetchSessionUsage(sid)
      .then((u) => setUsage(u))
      .catch(() => {
        /* 静默: 指示器是增强信息 */
      });
  };

  useEffect(() => {
    load(sessionId);
    if (!sessionId) return;
    const timer = window.setInterval(() => load(sessionId), 60_000);
    return () => window.clearInterval(timer);
  }, [sessionId, refreshKey]);

  useEffect(() => {
    const prev = prevStreamingIdRef.current;
    prevStreamingIdRef.current = streamingMessageId;
    if (prev !== null && streamingMessageId === null && sessionId) {
      load(sessionId);
    }
  }, [streamingMessageId, sessionId]);

  // 弹层外点/Escape 关闭
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

  if (!sessionId || !usage || usage.last_prompt_tokens == null) return null;

  // 窗口解析: catalog 值优先; 后端已按用户 autoContext/maxContext 计算。
  const windowTokens = resolvedContextWindow(usage.effective_context_window);
  const used = usage.last_prompt_tokens;
  const pct = windowTokens > 0 ? Math.min(1, used / windowTokens) : 0;
  const { bar, text } = toneClass(pct);
  const cached = usage.last_cached_tokens ?? 0;
  const breakdown: ContextBreakdown | null = usage.last_context_breakdown ?? null;
  const categories = breakdown?.categories ?? {};
  const categoryTotal = Object.values(categories).reduce((a, b) => a + (b || 0), 0);
  const shownTotal = categoryTotal > 0 ? categoryTotal : used;
  const remaining = Math.max(0, windowTokens - used);

  const title = [
    `上下文约 ${formatTokens(used)} / ${formatTokens(windowTokens)} tokens (${Math.round(pct * 100)}%)`,
    usage.last_model ? `模型: ${usage.last_model}` : null,
    cached > 0 ? `其中缓存命中 ${formatTokens(cached)}` : null,
    '点击展开各部分占用明细',
  ]
    .filter(Boolean)
    .join('\n');

  return (
    <span className="relative shrink-0" ref={panelRef}>
      <button
        type="button"
        className="flex items-center gap-1.5 text-[11px] text-text-secondary hover:text-text-primary"
        title={title}
        aria-expanded={open}
        data-testid="context-meter"
        onClick={() => setOpen((v) => !v)}
      >
        <span className="relative h-1.5 w-16 overflow-hidden rounded-full bg-bg-muted">
          <span
            className={`absolute inset-y-0 left-0 rounded-full ${bar}`}
            style={{ width: `${Math.max(2, Math.round(pct * 100))}%` }}
          />
        </span>
        <span className={pct >= 0.9 ? text : undefined}>{Math.round(pct * 100)}%</span>
      </button>

      {open && (
        <span
          className="absolute top-full right-0 z-50 mt-2 block w-80 rounded-lg border border-border bg-bg-primary p-3 text-left shadow-lg"
          data-testid="context-meter-popover"
        >
          <span className="mb-2 block text-xs font-medium text-text-primary">
            上下文占用 {formatTokens(used)} / {formatTokens(windowTokens)} tokens（
            {Math.round(pct * 100)}%）
            {usage.last_model ? ` · ${usage.last_model}` : ''}
          </span>

          {/* 堆叠条: 各类别按占窗口宽度分色块, 剩余为轨道底色 */}
          <span
            className="mb-2 flex h-2 w-full overflow-hidden rounded-full bg-bg-muted"
            data-testid="context-meter-stacked-bar"
          >
            {CATEGORY_META.map(({ key, color }) => {
              const tokens = categories[key] ?? 0;
              if (tokens <= 0 || windowTokens <= 0) return null;
              return (
                <span
                  key={key}
                  className={color}
                  style={{ width: `${(tokens / windowTokens) * 100}%` }}
                  title={`${key}: ${formatTokens(tokens)}`}
                />
              );
            })}
          </span>

          {categoryTotal > 0 ? (
            <span className="block">
              {CATEGORY_META.map(({ key, label, color }) => {
                const tokens = categories[key] ?? 0;
                if (tokens <= 0) return null;
                return (
                  <span
                    key={key}
                    className="flex items-center justify-between gap-2 py-0.5 text-[11px] text-text-secondary"
                  >
                    <span className="flex items-center gap-1.5">
                      <span className={`h-2 w-2 rounded-full ${color}`} />
                      {label}
                    </span>
                    <span className="tabular-nums">
                      {formatTokens(tokens)} ·{' '}
                      {Math.round((tokens / Math.max(1, shownTotal)) * 100)}%
                    </span>
                  </span>
                );
              })}
              {remaining > 0 && (
                <span className="flex items-center justify-between gap-2 py-0.5 text-[11px] text-text-muted">
                  <span className="flex items-center gap-1.5">
                    <span className="h-2 w-2 rounded-full bg-bg-muted ring-1 ring-border" />
                    剩余空间
                  </span>
                  <span className="tabular-nums">
                    {formatTokens(remaining)} ·{' '}
                    {Math.round((remaining / Math.max(1, windowTokens)) * 100)}%
                  </span>
                </span>
              )}
              <span className="mt-1.5 block border-t border-border pt-1.5 text-[10px] text-text-muted">
                {breakdown?.calibrated
                  ? '按上一轮请求 provider 实报 prompt 等比校准的分类估算'
                  : '本地估算口径（未获 provider 实报校准），仅示意占比'}
                {cached > 0 ? ` · 缓存命中 ${formatTokens(cached)}` : ''}
              </span>
            </span>
          ) : (
            <span className="block text-[11px] text-text-muted">
              暂无分类明细（该请求记录早于明细分桶上线，或明细采集失败）。
            </span>
          )}
        </span>
      )}
    </span>
  );
}
