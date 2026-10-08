// src/widgets/chat/TrajectoryPane.tsx
//
// 对标 F3/F4（ZCode ModelTrajectoryPane 一期 + 二期增强）：会话级模型轨迹面板。
// - 顶部汇总遥测条（总步数 / 工具调用数 / Token 吞吐 / 累计耗时）
// - 角色与工具快筛胶囊（全部 / 用户 / 模型 / 含工具）+ 搜索过滤
// - 相对耗时热度条 + 展开详情（input/output tokens、工具 payload、一键复制 JSON）

import { useMemo, useState } from 'react';

import { requestMessageJump } from '../../features/chat/messageJumpStore';
import {
  useConversationTrajectory,
  type TrajectoryEntry,
} from '../../features/chat/useConversationTrajectory';

type FilterKind = 'all' | 'user' | 'assistant' | 'tool';

const ROLE_BADGE: Record<TrajectoryEntry['role'], { label: string; className: string }> = {
  user: { label: '用户', className: 'bg-blue-500/15 text-blue-500' },
  assistant: { label: '模型', className: 'bg-green-500/15 text-green-600' },
  tool: { label: '工具', className: 'bg-amber-500/15 text-amber-600' },
  system: { label: '系统', className: 'bg-bg-muted text-text-secondary' },
};

const FILTER_OPTIONS: ReadonlyArray<{ id: FilterKind; label: string }> = [
  { id: 'all', label: '全部' },
  { id: 'user', label: '用户' },
  { id: 'assistant', label: '模型' },
  { id: 'tool', label: '含工具' },
];

function formatTime(createdAt: number): string {
  try {
    return new Date(createdAt).toLocaleTimeString('zh-CN', { hour12: false });
  } catch {
    return '';
  }
}

function truncate(text: string, max: number): string {
  const flat = text.replace(/\s+/g, ' ').trim();
  return flat.length <= max ? flat : flat.slice(0, max) + '…';
}

interface TrajectoryPaneProps {
  sessionId: string | null;
}

export function TrajectoryPane({ sessionId }: TrajectoryPaneProps) {
  const { items, summary } = useConversationTrajectory(sessionId);
  const [query, setQuery] = useState('');
  const [roleFilter, setRoleFilter] = useState<FilterKind>('all');
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [copiedId, setCopiedId] = useState<string | null>(null);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return items.filter((e) => {
      if (roleFilter === 'user' && e.role !== 'user') return false;
      if (roleFilter === 'assistant' && e.role !== 'assistant') return false;
      if (roleFilter === 'tool' && e.toolCallCount === 0 && e.role !== 'tool') return false;
      if (!q) return true;
      return (
        e.preview.toLowerCase().includes(q) ||
        (e.reasoningPreview ?? '').toLowerCase().includes(q) ||
        e.toolCalls.some((tc) => tc.name.toLowerCase().includes(q))
      );
    });
  }, [items, query, roleFilter]);

  const handleSelect = (entry: TrajectoryEntry) => {
    setExpandedId((cur) => (cur === entry.messageId ? null : entry.messageId));
    requestMessageJump({ messageId: entry.messageId });
  };

  const handleCopyJson = (entry: TrajectoryEntry) => {
    const payload = JSON.stringify(
      {
        messageId: entry.messageId,
        role: entry.role,
        model: entry.model,
        stepIndex: entry.stepIndex,
        inputTokens: entry.inputTokens,
        outputTokens: entry.totalTokens,
        latencyMs: entry.latencyMs,
        finishReason: entry.finishReason,
        toolCalls: entry.toolCalls,
      },
      null,
      2,
    );
    void navigator.clipboard?.writeText?.(payload);
    setCopiedId(entry.messageId);
  };

  return (
    <div className="py-2" data-testid="trajectory-pane">
      <div className="px-3 pb-2 space-y-1.5">
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="搜索轨迹（内容 / 推理 / 工具名）"
          data-testid="trajectory-search"
          className="w-full px-2 py-1 text-sm rounded border border-border bg-bg-muted focus:outline-none focus:ring-1 focus:ring-ring"
        />
        {items.length > 0 && (
          <>
            <div className="flex items-center gap-1 flex-wrap" data-testid="trajectory-filters">
              {FILTER_OPTIONS.map((opt) => (
                <button
                  key={opt.id}
                  type="button"
                  data-testid={`trajectory-filter-${opt.id}`}
                  aria-pressed={roleFilter === opt.id}
                  onClick={() => setRoleFilter(opt.id)}
                  className={`px-2 py-0.5 rounded text-[11px] transition-colors ${
                    roleFilter === opt.id
                      ? 'bg-primary/15 text-primary font-medium'
                      : 'bg-bg-muted text-muted hover:text-text'
                  }`}
                >
                  {opt.label}
                </button>
              ))}
            </div>
            <div
              className="text-[10px] text-muted flex items-center gap-2 flex-wrap"
              data-testid="trajectory-summary"
            >
              <span>{summary.totalEntries} 条轨迹</span>
              {summary.totalToolCalls > 0 && <span>工具 ×{summary.totalToolCalls}</span>}
              {(summary.totalInputTokens > 0 || summary.totalOutputTokens > 0) && (
                <span>
                  Token {summary.totalInputTokens} in / {summary.totalOutputTokens} out
                </span>
              )}
              {summary.totalLatencyMs > 0 && <span>总耗时 {summary.totalLatencyMs} ms</span>}
            </div>
          </>
        )}
      </div>
      {items.length === 0 ? (
        <div className="p-3 text-sm text-muted flex flex-col items-center gap-2">
          <div>暂无轨迹</div>
          <div className="text-xs text-center">对话开始后这里会列出完整模型轨迹</div>
        </div>
      ) : filtered.length === 0 ? (
        <div className="p-3 text-sm text-muted text-center">无匹配轨迹</div>
      ) : (
        filtered.map((entry) => {
          const badge = ROLE_BADGE[entry.role];
          const expanded = expandedId === entry.messageId;
          const latencyRatio =
            typeof entry.latencyMs === 'number' && summary.maxLatencyMs > 0
              ? Math.max(6, Math.round((entry.latencyMs / summary.maxLatencyMs) * 100))
              : null;
          return (
            <div key={entry.messageId}>
              <button
                type="button"
                className="w-full text-left px-3 py-1.5 hover:bg-bg-hover transition-colors"
                data-testid="trajectory-entry"
                onClick={() => handleSelect(entry)}
              >
                <div className="flex items-center gap-2">
                  <span
                    className={`inline-flex items-center px-1.5 h-5 rounded text-[10px] ${badge.className}`}
                  >
                    {badge.label}
                  </span>
                  <span className="text-sm truncate text-text-secondary flex-1">
                    {entry.preview}
                  </span>
                </div>
                <div className="mt-0.5 text-[10px] text-muted truncate">
                  {[
                    formatTime(entry.createdAt),
                    entry.model,
                    typeof entry.stepIndex === 'number' ? `step ${entry.stepIndex}` : null,
                    entry.toolCallCount > 0 ? `工具 ×${entry.toolCallCount}` : null,
                    typeof entry.inputTokens === 'number' ? `in ${entry.inputTokens}` : null,
                    typeof entry.totalTokens === 'number' ? `${entry.totalTokens} tok` : null,
                    typeof entry.latencyMs === 'number' ? `${entry.latencyMs} ms` : null,
                  ]
                    .filter(Boolean)
                    .join(' · ')}
                </div>
                {latencyRatio !== null && (
                  <div className="mt-1 h-1 w-full rounded bg-bg-muted overflow-hidden">
                    <div
                      data-testid="trajectory-latency-bar"
                      className="h-full bg-amber-500/60 rounded"
                      style={{ width: `${latencyRatio}%` }}
                    />
                  </div>
                )}
              </button>
              {expanded && (
                <div
                  className="mx-3 mb-1.5 p-2 rounded bg-bg-muted text-xs space-y-1.5"
                  data-testid="trajectory-detail"
                >
                  <div className="flex items-center justify-between">
                    <span className="text-[10px] text-muted font-mono">{entry.messageId}</span>
                    <button
                      type="button"
                      data-testid="trajectory-copy-json"
                      onClick={() => handleCopyJson(entry)}
                      className="px-1.5 py-0.5 rounded text-[10px] bg-bg hover:bg-bg-hover text-text-secondary"
                    >
                      {copiedId === entry.messageId ? '已复制' : '复制 JSON'}
                    </button>
                  </div>
                  {entry.reasoningContent && (
                    <div>
                      <div className="text-muted mb-0.5">推理</div>
                      <div className="whitespace-pre-wrap break-words text-text-secondary">
                        {entry.reasoningContent}
                      </div>
                    </div>
                  )}
                  {entry.toolCalls.map((tc, i) => (
                    <div key={tc.id ?? i}>
                      <div className="text-muted mb-0.5">
                        工具 {i + 1}: {tc.name}
                      </div>
                      <div className="font-mono break-all text-text-secondary">
                        {truncate(JSON.stringify(tc.args ?? {}), 500)}
                      </div>
                      {tc.result && (
                        <div className="font-mono break-all text-muted">
                          → {truncate(tc.result, 500)}
                        </div>
                      )}
                    </div>
                  ))}
                  {entry.finishReason && (
                    <div className="text-muted">finish: {entry.finishReason}</div>
                  )}
                  {(entry.hasCompactInfo || entry.hasSkills || entry.hasMemoryRefs) && (
                    <div className="text-muted">
                      {[
                        entry.hasSkills ? '技能激活' : null,
                        entry.hasMemoryRefs ? '记忆召回' : null,
                        entry.hasCompactInfo ? '上下文压缩' : null,
                      ]
                        .filter(Boolean)
                        .join(' / ')}
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })
      )}
    </div>
  );
}
