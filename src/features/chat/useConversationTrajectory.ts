// src/features/chat/useConversationTrajectory.ts
//
// 对标 F3/F4（ZCode ModelTrajectoryPane 一期 + 二期遥测增强）：会话级模型轨迹数据源。
// 从 messages store 派生整段会话的轨迹条目：角色、预览、模型、步序、
// 工具调用数、input/output token 用量、耗时、reasoning 摘要，并计算会话级汇总遥测。

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
  /** generation_stats.input_tokens（仅 assistant 终稿） */
  inputTokens?: number;
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

export interface TrajectorySummary {
  totalEntries: number;
  totalToolCalls: number;
  totalInputTokens: number;
  totalOutputTokens: number;
  totalLatencyMs: number;
  maxLatencyMs: number;
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
 * 获取当前会话的模型轨迹条目与汇总遥测（按消息顺序，含 user/assistant/tool/system）。
 */
export function useConversationTrajectory(sessionId: string | null): {
  items: TrajectoryEntry[];
  summary: TrajectorySummary;
} {
  const messages = useStore((s) => s.messages);

  return useMemo(() => {
    const emptySummary: TrajectorySummary = {
      totalEntries: 0,
      totalToolCalls: 0,
      totalInputTokens: 0,
      totalOutputTokens: 0,
      totalLatencyMs: 0,
      maxLatencyMs: 0,
    };
    if (!sessionId) return { items: [], summary: emptySummary };

    const entries: TrajectoryEntry[] = [];
    let totalToolCalls = 0;
    let totalInputTokens = 0;
    let totalOutputTokens = 0;
    let totalLatencyMs = 0;
    let maxLatencyMs = 0;

    for (const msg of messages) {
      if (msg.session_id !== sessionId) continue;
      if (msg.subtype === 'topic_separator') continue;

      const toolCalls = parseToolCalls(msg.tool_calls);
      const stats = msg.generation_stats ?? null;
      const inputTokens =
        stats && typeof stats.input_tokens === 'number' ? stats.input_tokens : undefined;
      const totalTokens =
        stats && typeof stats.output_tokens === 'number' ? stats.output_tokens : undefined;
      const latencyMs =
        stats && typeof stats.latency_ms === 'number' ? stats.latency_ms : undefined;

      totalToolCalls += toolCalls.length;
      if (typeof inputTokens === 'number') totalInputTokens += inputTokens;
      if (typeof totalTokens === 'number') totalOutputTokens += totalTokens;
      if (typeof latencyMs === 'number') {
        totalLatencyMs += latencyMs;
        if (latencyMs > maxLatencyMs) maxLatencyMs = latencyMs;
      }

      entries.push({
        messageId: msg.id,
        role: msg.role,
        preview: toPreview(msg.content || (toolCalls.length ? `[工具调用 ×${toolCalls.length}]` : '')),
        createdAt: msg.created_at,
        stepIndex: msg.step_index,
        model: msg.model,
        provider: msg.provider,
        finishReason: msg.finish_reason,
        inputTokens,
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

    return {
      items: entries,
      summary: {
        totalEntries: entries.length,
        totalToolCalls,
        totalInputTokens,
        totalOutputTokens,
        totalLatencyMs,
        maxLatencyMs,
      },
    };
  }, [messages, sessionId]);
}
