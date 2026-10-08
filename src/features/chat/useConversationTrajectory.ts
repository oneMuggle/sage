// src/features/chat/useConversationTrajectory.ts
//
// 对标 F3（ZCode ModelTrajectoryPane）：会话级模型轨迹数据源。
// 从 messages store 派生整段会话的轨迹条目：角色、预览、模型、步序、
// 工具调用数、token 用量、耗时、reasoning 摘要——全部来自前端已有数据，
// 不依赖新增后端端点（session_events 查询 API 留待 DSH 拆分收口后另批）。

import { useMemo } from 'react';

import { useStore, type ToolCall } from '../../shared/lib/store';

/** 轨迹条目预览文本的最大字符数（换行折叠为空格） */
export const TRAJECTORY_PREVIEW_MAX_CHARS = 60;

export interface TrajectoryEntry {
  messageId: string;
  role: 'user' | 'assistant' | 'system' | 'tool';
  /** 内容预览（换行折叠、超长截断加 …） */
  preview: string;
  createdAt: number;
  /** 多步 ReAct 步序号（null=旧消息/单步） */
  stepIndex?: number | null;
  model?: string;
  provider?: string;
  finishReason?: string | null;
  /** generation_stats.output_tokens（仅 assistant 终稿） */
  totalTokens?: number;
  /** generation_stats.latency_ms（仅 assistant 终稿） */
  latencyMs?: number;
  /** tool_calls 解析后条数（wire 字符串解析失败记 0） */
  toolCallCount: number;
  /** 解析后的 tool_calls（供详情展开 payload） */
  toolCalls: ToolCall[];
  /** reasoning_content 折叠摘要 */
  reasoningPreview?: string;
  /** 完整 reasoning（详情展开用） */
  reasoningContent?: string;
  hasMemoryRefs: boolean;
  hasSkills: boolean;
  hasCompactInfo: boolean;
}

function toPreview(text: string): string {
  const flat = text.replace(/\s+/g, ' ').trim();
  if (flat.length <= TRAJECTORY_PREVIEW_MAX_CHARS) return flat;
  return flat.slice(0, TRAJECTORY_PREVIEW_MAX_CHARS) + '…';
}

/** tool_calls wire 兼容解析：数组直用，JSON 字符串尝试 parse（失败为空） */
function parseToolCalls(toolCalls: ToolCall[] | string | null | undefined): ToolCall[] {
  if (!toolCalls) return [];
  if (Array.isArray(toolCalls)) return toolCalls;
  try {
    const parsed = JSON.parse(toolCalls);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

/**
 * 获取当前会话的模型轨迹条目（按消息顺序，含 user/assistant/tool/system）。
 */
export function useConversationTrajectory(sessionId: string | null): {
  items: TrajectoryEntry[];
} {
  const messages = useStore((s) => s.messages);

  const items = useMemo(() => {
    if (!sessionId) return [];

    const entries: TrajectoryEntry[] = [];

    for (const msg of messages) {
      if (msg.session_id !== sessionId) continue;
      // 话题段切换 marker 不属于模型轨迹
      if (msg.subtype === 'topic_separator') continue;

      const toolCalls = parseToolCalls(msg.tool_calls);
      const stats = msg.generation_stats ?? null;
      const totalTokens =
        stats && typeof stats.output_tokens === 'number' ? stats.output_tokens : undefined;
      const latencyMs =
        stats && typeof stats.latency_ms === 'number' ? stats.latency_ms : undefined;

      entries.push({
        messageId: msg.id,
        role: msg.role,
        preview: toPreview(msg.content || (toolCalls.length ? `[工具调用 ×${toolCalls.length}]` : '')),
        createdAt: msg.created_at,
        stepIndex: msg.step_index,
        model: msg.model,
        provider: msg.provider,
        finishReason: msg.finish_reason,
        totalTokens,
        latencyMs,
        toolCallCount: toolCalls.length,
        toolCalls,
        reasoningPreview: msg.reasoning_content ? toPreview(msg.reasoning_content) : undefined,
        reasoningContent: msg.reasoning_content || undefined,
        hasMemoryRefs: Boolean(msg.memory_refs?.length),
        hasSkills: Boolean(msg.activated_skills?.length),
        hasCompactInfo: Boolean(msg.compact_info),
      });
    }

    return entries;
  }, [messages, sessionId]);

  return { items };
}
