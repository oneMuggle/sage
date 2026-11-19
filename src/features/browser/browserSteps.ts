/**
 * 浏览器面板步骤数据源（C2）。
 *
 * 面板时间线不能再只看 `streamingToolCalls`：`finalizeStep`（step_done）和
 * `finishStream` 都会把它清空。这里把**持久化消息里的 tool_calls**（step_done
 * 已逐条写入 assistant 消息）与实时切片合并：
 *
 * - 只保留 `browser_*` 工具；
 * - 按 `id` 去重（实时切片胜出，保留最新 result）；
 * - 持久化消息按 store 顺序在前，实时切片在后，天然是按发生时间的顺序。
 */

import type { Message, ToolCall } from '../../shared/lib/store';

function messageToolCalls(message: Message): ToolCall[] {
  const raw = message.tool_calls;
  if (!raw) return [];
  if (Array.isArray(raw)) return raw;
  try {
    const parsed: unknown = JSON.parse(raw);
    return Array.isArray(parsed) ? (parsed as ToolCall[]) : [];
  } catch {
    return [];
  }
}

/** 收集某对话持久化消息中的浏览器工具调用（按消息顺序）。 */
export function collectPersistedBrowserCalls(
  messages: readonly Message[],
  conversationId: string | null,
): ToolCall[] {
  if (!conversationId) return [];
  const calls: ToolCall[] = [];
  for (const message of messages) {
    if (message.session_id !== conversationId) continue;
    for (const call of messageToolCalls(message)) {
      if (call && typeof call.name === 'string' && call.name.startsWith('browser_')) {
        calls.push(call);
      }
    }
  }
  return calls;
}

function callKey(call: ToolCall): string {
  if (call.id) return `id:${call.id}`;
  return `anon:${call.name}:${JSON.stringify(call.args ?? {})}`;
}

/** 合并持久化与实时切片：去重、实时版本覆盖旧 result、保持时间顺序。 */
export function mergeBrowserToolCalls(
  persisted: readonly ToolCall[],
  live: readonly ToolCall[],
): ToolCall[] {
  const merged: ToolCall[] = [];
  const indexByKey = new Map<string, number>();
  const push = (call: ToolCall): void => {
    const key = callKey(call);
    const existing = indexByKey.get(key);
    if (existing !== undefined) {
      merged[existing] = call;
      return;
    }
    indexByKey.set(key, merged.length);
    merged.push(call);
  };
  persisted.forEach(push);
  live.forEach(push);
  return merged;
}

/** 从浏览器工具调用中取最近一次的会话 id。 */
export function latestBrowserSessionId(calls: readonly ToolCall[]): string | null {
  for (let i = calls.length - 1; i >= 0; i -= 1) {
    const result = calls[i].result;
    if (!result) continue;
    try {
      const parsed = JSON.parse(result) as Record<string, unknown>;
      const content =
        parsed.content && typeof parsed.content === 'object'
          ? (parsed.content as Record<string, unknown>)
          : {};
      const meta = (content.browser_meta ?? parsed.browser_meta) as
        | Record<string, unknown>
        | undefined;
      const sessionId = meta?.session_id;
      if (typeof sessionId === 'string' && sessionId) return sessionId;
    } catch {
      // 平面错误字符串没有 meta：继续向前找
    }
  }
  return null;
}
