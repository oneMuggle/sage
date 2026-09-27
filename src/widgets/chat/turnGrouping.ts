import type { Message } from '../../shared/lib/store';

/**
 * Turn 分组：将消息序列按对话轮次分组，用于折叠显示。
 *
 * 分组规则：
 * - user 消息开启新 Turn
 * - assistant / tool 消息归入当前 Turn
 * - topic_separator / system 消息独立渲染（不参与分组）
 * - 孤立的 assistant（无前置 user）归入一个虚拟 Turn
 */

export type TurnItem =
  | { kind: 'turn'; id: string; messages: Message[] }
  | { kind: 'standalone'; id: string; message: Message };

export function groupMessagesIntoTurns(messages: Message[]): TurnItem[] {
  const items: TurnItem[] = [];
  let current: { id: string; messages: Message[] } | null = null;

  for (const msg of messages) {
    if (msg.subtype === 'topic_separator') {
      if (current) {
        items.push({ kind: 'turn', id: current.id, messages: current.messages });
        current = null;
      }
      items.push({ kind: 'standalone', id: msg.id, message: msg });
    } else if (msg.role === 'user') {
      if (current) {
        items.push({ kind: 'turn', id: current.id, messages: current.messages });
      }
      current = { id: `turn-${msg.id}`, messages: [msg] };
    } else if (msg.role === 'assistant' || msg.role === 'tool') {
      if (!current) {
        current = { id: `turn-orphan-${msg.id}`, messages: [msg] };
      } else {
        current.messages.push(msg);
      }
    } else {
      // system / error → standalone
      if (current) {
        items.push({ kind: 'turn', id: current.id, messages: current.messages });
        current = null;
      }
      items.push({ kind: 'standalone', id: msg.id, message: msg });
    }
  }

  if (current) {
    items.push({ kind: 'turn', id: current.id, messages: current.messages });
  }

  return items;
}

/** Turn 是否可折叠：包含 >= 3 条 assistant/tool 消息时启用折叠（2 条及以下保持展开，避免隐藏有用信息） */
export function isTurnCollapsible(messages: Message[]): boolean {
  const assistantOrToolCount = messages.filter(
    (m) => m.role === 'assistant' || m.role === 'tool',
  ).length;
  return assistantOrToolCount >= 3;
}

/** 提取 Turn 中最终的用户可见文本摘要（用于折叠态预览） */
export function getTurnSummary(messages: Message[], maxLen = 180): string {
  for (let i = messages.length - 1; i >= 0; i--) {
    const msg = messages[i];
    if (msg.role === 'assistant' && msg.content?.trim()) {
      const text = msg.content.replace(/```[\s\S]*?```/g, '[代码块]').trim();
      return text.length > maxLen ? text.slice(0, maxLen) + '…' : text;
    }
  }
  return '';
}

/** 统计 Turn 中的工具调用数量 */
export function getTurnToolCallCount(messages: Message[]): number {
  let count = 0;
  for (const msg of messages) {
    if (msg.role === 'assistant' && msg.tool_calls) {
      const calls =
        typeof msg.tool_calls === 'string'
          ? (() => {
              try {
                return JSON.parse(msg.tool_calls as string);
              } catch {
                return [];
              }
            })()
          : msg.tool_calls;
      count += Array.isArray(calls) ? calls.length : 0;
    }
  }
  return count;
}
