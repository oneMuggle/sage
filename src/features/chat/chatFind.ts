// src/features/chat/chatFind.ts
//
// 对话阅读体验 B4（docs/mcp-chat-reading-nav-optimization.md §10.3 / §10.4）：
// 会话内查找的纯逻辑。在当前会话的全部消息（包括尾窗外尚未渲染的）里统计
// 查找词的出现次数，生成按消息顺序排列的命中列表。计数基于去掉 Markdown
// 标记后的文本（markdownText），与气泡里看到的文字基本一致。

import { markdownToPlainText } from './markdownText';

/** Layout 在 Ctrl/Cmd+F 时派发的可取消事件；查找栏处理后 preventDefault() */
export const CHAT_FIND_EVENT = 'sage:open-chat-find';
/** 侧栏会话搜索框的聚焦事件（ConversationsSection 监听） */
export const FOCUS_SEARCH_EVENT = 'sage:focus-search';

/**
 * Ctrl/Cmd+F 的分发（Layout 调用）：先派发可取消的 CHAT_FIND_EVENT，会话内查找栏
 * 接管（preventDefault）则到此为止；没有被接管（不在聊天页、会话为空）或按住
 * Shift 时聚焦侧栏会话搜索。返回是否交给了会话内查找。
 */
export function dispatchFindShortcut(shiftKey: boolean): boolean {
  const handled =
    !shiftKey && !window.dispatchEvent(new CustomEvent(CHAT_FIND_EVENT, { cancelable: true }));
  if (!handled) window.dispatchEvent(new CustomEvent(FOCUS_SEARCH_EVENT));
  return handled;
}

export interface FindableMessage {
  id: string;
  role: string;
  content: string;
  subtype?: string | null;
}

export interface FindMatch {
  messageId: string;
  /** 该消息内的第几处命中（0 起） */
  occurrence: number;
}

// 按消息对象缓存可见文本：流式输出时只有正在生成的那条会换新对象，
// 其余消息复用缓存，避免每个 token 都把整段会话重新剥离一遍。
const plainTextCache = new WeakMap<FindableMessage, string>();

function plainTextOf(message: FindableMessage): string {
  let text = plainTextCache.get(message);
  if (text === undefined) {
    text = markdownToPlainText(message.content ?? '').toLowerCase();
    plainTextCache.set(message, text);
  }
  return text;
}

/** 不重叠、不区分大小写的出现次数 */
export function countOccurrences(haystack: string, needle: string): number {
  if (!needle) return 0;
  let count = 0;
  for (
    let at = haystack.indexOf(needle);
    at !== -1;
    at = haystack.indexOf(needle, at + needle.length)
  ) {
    count += 1;
  }
  return count;
}

/** 只查 user / assistant 的正文；分隔线、系统通知、工具行不参与 */
function isSearchable(message: FindableMessage): boolean {
  return (
    (message.role === 'user' || message.role === 'assistant') &&
    message.subtype !== 'topic_separator'
  );
}

export function buildFindMatches(
  messages: ReadonlyArray<FindableMessage>,
  query: string,
): FindMatch[] {
  const needle = query.trim().toLowerCase();
  if (!needle) return [];
  const matches: FindMatch[] = [];
  for (const message of messages) {
    if (!isSearchable(message)) continue;
    const count = countOccurrences(plainTextOf(message), needle);
    for (let occurrence = 0; occurrence < count; occurrence += 1) {
      matches.push({ messageId: message.id, occurrence });
    }
  }
  return matches;
}
