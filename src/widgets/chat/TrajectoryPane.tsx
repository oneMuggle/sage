// src/widgets/chat/TrajectoryPane.tsx
//
// 对标 F3（ZCode ModelTrajectoryPane）：会话级模型轨迹面板。
// 时间线（按消息序）+ 搜索（preview/reasoning/工具名）+ 角色徽标 +
// 可展开详情（reasoning 全文 / 工具 payload / 用量耗时）。
// 点击条目经 messageJumpStore 定位到消息本体（与 U1 轮次导航一致）。
// 样式与 TurnList/ConversationOutline 同族（px-3/py-1.5/truncate/hover）。

import { useMemo, useState } from 'react';

import { requestMessageJump } from '../../features/chat/messageJumpStore';
import {
  useConversationTrajectory,
  type TrajectoryEntry,
} from '../../features/chat/useConversationTrajectory';

const ROLE_BADGE: Record<TrajectoryEntry['role'], { label: string; className: string }> = {
  user: { label: '用户', className: 'bg-blue-500/15 text-blue-500' },
  assistant: { label: '模型', className: 'bg-green-500/15 text-green-600' },
  tool: { label: '工具', className: 'bg-amber-500/15 text-amber-600' },
  system: { label: '系统', className: 'bg-bg-muted text-text-secondary' },
};

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
  const { items } = useConversationTrajectory(sessionId);
  const [query, setQuery] = useState('');
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return items;
    return items.filter(
      (e) =>
        e.preview.toLowerCase().includes(q) ||
        (e.reasoningPreview ?? '').toLowerCase().includes(q) ||
        e.toolCalls.some((tc) => tc.name.toLowerCase().includes(q)),
    );
  }, [items, query]);

  const handleSelect = (entry: TrajectoryEntry) => {
    setExpandedId((cur) => (cur === entry.messageId ? null : entry.messageId));
    requestMessageJump({ messageId: entry.messageId });
  };

  return (
    <div className="py-2" data-testid="trajectory-pane">
      <div className="px-3 pb-2">
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="搜索轨迹（内容 / 推理 / 工具名）"
          data-testid="trajectory-search"
          className="w-full px-2 py-1 text-sm rounded border border-border bg-bg-muted focus:outline-none focus:ring-1 focus:ring-ring"
        />
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
                    typeof entry.totalTokens === 'number' ? `${entry.totalTokens} tok` : null,
                    typeof entry.latencyMs === 'number' ? `${entry.latencyMs} ms` : null,
                  ]
                    .filter(Boolean)
                    .join(' · ')}
                </div>
              </button>
              {expanded && (
                <div
                  className="mx-3 mb-1.5 p-2 rounded bg-bg-muted text-xs space-y-1.5"
                  data-testid="trajectory-detail"
                >
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
