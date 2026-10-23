import type { ToolCall } from './store';

/** 后端拦截信封（agent.py 失败分支对 web_fetch 类工具的结构化输出） */
interface ToolResultEnvelope {
  content?: unknown;
  metadata?: Record<string, unknown>;
}

/**
 * R19-W1: 归一化工具结果信封。
 *
 * 后端在网页访问被拦截时把 ToolResult 包装成
 * `{"content": "<可读文案>", "metadata": {"blockReason": ..., "blockedUrl": ...,
 * "suggestedActions": [...]}}` 字符串下发（见 agent.py 失败分支）。若不归一化：
 * - 直播路径：气泡里显示裸 JSON
 * - 重载路径：session_repo 把整串原样落库，回读后 metadata 丢失 → 卡片无法渲染
 *
 * 两条路径共用此函数：提取 content 作为 result，把信封 metadata 合并进
 * ToolCall.metadata，使拦截卡片在直播与历史回读下表现一致。
 *
 * 非信封（普通字符串结果）原样返回，不产生任何行为变化。
 */
export function normalizeToolCallEnvelope(tc: ToolCall): ToolCall {
  const raw = tc.result;
  if (typeof raw !== 'string' || !raw || raw[0] !== '{') return tc;

  let parsed: ToolResultEnvelope;
  try {
    parsed = JSON.parse(raw) as ToolResultEnvelope;
  } catch {
    return tc;
  }
  if (!parsed || typeof parsed !== 'object' || !parsed.metadata) return tc;

  const blockReason = parsed.metadata.blockReason;
  if (typeof blockReason !== 'string' || !blockReason) return tc;

  return {
    ...tc,
    result: typeof parsed.content === 'string' && parsed.content ? parsed.content : raw,
    metadata: { ...tc.metadata, ...parsed.metadata },
  };
}
