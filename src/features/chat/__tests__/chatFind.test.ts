// 对话阅读体验 B4：会话内查找的纯逻辑 —— 命中列表、计数口径、快捷键分发。
import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  buildFindMatches,
  CHAT_FIND_EVENT,
  countOccurrences,
  dispatchFindShortcut,
  FOCUS_SEARCH_EVENT,
} from '../chatFind';

const messages = [
  { id: 'u1', role: 'user', content: '怎么配置 **Sage** 的代理？' },
  {
    id: 'a1',
    role: 'assistant',
    content: '打开 [Sage 设置](https://x.dev/sage) → 代理。sage sage',
  },
  { id: 's1', role: 'system', content: 'sage 系统消息' },
  { id: 't1', role: 'assistant', subtype: 'topic_separator', content: 'sage' },
];

describe('buildFindMatches (B4)', () => {
  it('lists matches in message order over the visible text of user / assistant messages', () => {
    expect(buildFindMatches(messages, ' SAGE ')).toEqual([
      { messageId: 'u1', occurrence: 0 },
      { messageId: 'a1', occurrence: 0 },
      { messageId: 'a1', occurrence: 1 },
      { messageId: 'a1', occurrence: 2 },
    ]);
  });

  it('returns nothing for a blank query', () => {
    expect(buildFindMatches(messages, '   ')).toEqual([]);
  });

  it('counts non-overlapping occurrences', () => {
    expect(countOccurrences('aaaa', 'aa')).toBe(2);
    expect(countOccurrences('abc', '')).toBe(0);
  });

  it('sees updated content once the message object is replaced (streaming)', () => {
    const first = { id: 'm', role: 'assistant', content: 'foo' };
    expect(buildFindMatches([first], 'foo')).toHaveLength(1);
    expect(buildFindMatches([{ ...first, content: 'foo foo' }], 'foo')).toHaveLength(2);
  });
});

describe('dispatchFindShortcut', () => {
  const focusSearch = vi.fn();
  const claim = (event: Event) => event.preventDefault();

  afterEach(() => {
    window.removeEventListener(CHAT_FIND_EVENT, claim);
    window.removeEventListener(FOCUS_SEARCH_EVENT, focusSearch);
    focusSearch.mockReset();
  });

  it('hands Ctrl+F to the in-chat find bar when it claims the event', () => {
    window.addEventListener(CHAT_FIND_EVENT, claim);
    window.addEventListener(FOCUS_SEARCH_EVENT, focusSearch);
    expect(dispatchFindShortcut(false)).toBe(true);
    expect(focusSearch).not.toHaveBeenCalled();
  });

  it('focuses the sidebar search on Ctrl+Shift+F or when nobody claims Ctrl+F', () => {
    window.addEventListener(CHAT_FIND_EVENT, claim);
    window.addEventListener(FOCUS_SEARCH_EVENT, focusSearch);
    expect(dispatchFindShortcut(true)).toBe(false);
    expect(focusSearch).toHaveBeenCalledTimes(1);

    window.removeEventListener(CHAT_FIND_EVENT, claim);
    expect(dispatchFindShortcut(false)).toBe(false);
    expect(focusSearch).toHaveBeenCalledTimes(2);
  });
});
