// src/features/chat/__tests__/useConversationOutline.test.ts
//
// P2-3.10: 验证对话大纲 hook 的标题提取逻辑。
import { renderHook } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { useStore } from '../../../shared/lib/store';
import { useConversationOutline } from '../useConversationOutline';

// Mock store
vi.mock('../../../shared/lib/store', () => ({
  useStore: vi.fn(),
}));

function mockMessages(
  messages: Array<{ id: string; session_id: string; role: string; content: string }>,
) {
  (useStore as unknown as ReturnType<typeof vi.fn>).mockImplementation(
    (selector: (s: unknown) => unknown) => {
      const state = { messages, isLoading: false };
      return selector(state);
    },
  );
}

describe('useConversationOutline', () => {
  it('returns [] when sessionId is null', () => {
    mockMessages([]);
    const { result } = renderHook(() => useConversationOutline(null));
    expect(result.current.items).toEqual([]);
  });

  it('extracts h2 and h3 from assistant messages', () => {
    mockMessages([
      { id: 'm1', session_id: 's1', role: 'user', content: '# 用户消息' },
      {
        id: 'm2',
        session_id: 's1',
        role: 'assistant',
        content: '## 简介\n\n这是简介\n\n### 背景\n\n背景内容\n\n## 实现\n\n实现细节',
      },
    ]);
    const { result } = renderHook(() => useConversationOutline('s1'));
    expect(result.current.items).toEqual([
      { text: '简介', messageId: 'm2', level: 2 },
      { text: '背景', messageId: 'm2', level: 3 },
      { text: '实现', messageId: 'm2', level: 2 },
    ]);
  });

  it('ignores h1 and h4+ headings', () => {
    mockMessages([
      { id: 'm1', session_id: 's1', role: 'assistant', content: '# H1\n#### H4\n## H2' },
    ]);
    const { result } = renderHook(() => useConversationOutline('s1'));
    expect(result.current.items).toEqual([{ text: 'H2', messageId: 'm1', level: 2 }]);
  });

  it('ignores headings inside code blocks', () => {
    mockMessages([
      {
        id: 'm1',
        session_id: 's1',
        role: 'assistant',
        content: '## 真实标题\n\n```markdown\n## 代码块内标题\n```\n\n## 另一个真实标题',
      },
    ]);
    const { result } = renderHook(() => useConversationOutline('s1'));
    expect(result.current.items).toEqual([
      { text: '真实标题', messageId: 'm1', level: 2 },
      { text: '另一个真实标题', messageId: 'm1', level: 2 },
    ]);
  });

  it('filters by session_id and role', () => {
    mockMessages([
      { id: 'm1', session_id: 's1', role: 'assistant', content: '## S1 标题' },
      { id: 'm2', session_id: 's2', role: 'assistant', content: '## S2 标题' },
      { id: 'm3', session_id: 's1', role: 'user', content: '## 用户消息不提取' },
    ]);
    const { result } = renderHook(() => useConversationOutline('s1'));
    expect(result.current.items).toEqual([{ text: 'S1 标题', messageId: 'm1', level: 2 }]);
  });

  it('skips messages with empty content', () => {
    mockMessages([
      { id: 'm1', session_id: 's1', role: 'assistant', content: '' },
      { id: 'm2', session_id: 's1', role: 'assistant', content: '## 有内容' },
    ]);
    const { result } = renderHook(() => useConversationOutline('s1'));
    expect(result.current.items).toEqual([{ text: '有内容', messageId: 'm2', level: 2 }]);
  });
});
