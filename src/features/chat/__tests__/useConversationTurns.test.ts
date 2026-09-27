// src/features/chat/__tests__/useConversationTurns.test.ts
//
// 对标 U1（ZCode ConversationTurnNavigator）：轮次导航数据源单测。
// 覆盖: 普通 user 消息计轮、assistant/tool/topic_separator 不计、
// 序号 1 起、预览截断与换行折叠、跨会话过滤、空会话。

import { renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';

import { useStore } from '../../../shared/lib/store';
import type { Session } from '../../../shared/lib/store';
import {
  TURN_PREVIEW_MAX_CHARS,
  useConversationTurns,
} from '../useConversationTurns';


const sid = 's-turns';

function seedMessages(
  msgs: Array<{ id: string; role: 'user' | 'assistant' | 'tool'; content: string; subtype?: string | null }>,
): void {
  const now = Date.now();
  useStore.setState({
    sessions: [{ id: sid, title: 'T', created_at: now, updated_at: now, last_message_at: null, message_count: msgs.length, is_pinned: false } as Session],
    messages: msgs.map((m, i) => ({
      id: m.id,
      session_id: sid,
      role: m.role,
      content: m.content,
      created_at: now + i,
      model: undefined,
      provider: undefined,
      tool_calls: undefined,
      tool_call_id: undefined,
      reasoning_content: undefined,
      step_index: undefined,
      segment_id: 0,
      subtype: m.subtype ?? null,
      activated_skills: undefined,
      compact_info: undefined,
      memory_refs: undefined,
      rag_citations: undefined,
      sources: undefined,
      finish_reason: undefined,
      generation_stats: undefined,
    })),
    currentSessionId: sid,
  });
}

describe('useConversationTurns', () => {
  beforeEach(() => {
    useStore.setState({ messages: [], sessions: [] });
  });

  it('counts each plain user message as a turn, in order', () => {
    seedMessages([
      { id: 'u1', role: 'user', content: '第一问' },
      { id: 'a1', role: 'assistant', content: '## 标题\n回答' },
      { id: 'u2', role: 'user', content: '第二问' },
    ]);
    const { result } = renderHook(() => useConversationTurns(sid));
    expect(result.current.items).toHaveLength(2);
    expect(result.current.items[0]).toMatchObject({ index: 1, messageId: 'u1', preview: '第一问' });
    expect(result.current.items[1]).toMatchObject({ index: 2, messageId: 'u2', preview: '第二问' });
  });

  it('ignores topic_separator markers and tool messages', () => {
    seedMessages([
      { id: 'u1', role: 'user', content: '问' },
      { id: 'm', role: 'user', content: '段切换', subtype: 'topic_separator' },
      { id: 't', role: 'tool', content: '工具回显' },
    ]);
    const { result } = renderHook(() => useConversationTurns(sid));
    expect(result.current.items).toHaveLength(1);
    expect(result.current.items[0].messageId).toBe('u1');
  });

  it('folds whitespace and truncates long previews at 48 chars', () => {
    const long = 'a'.repeat(60) + '\n\n' + 'b'.repeat(10);
    seedMessages([{ id: 'u-long', role: 'user', content: long }]);
    const { result } = renderHook(() => useConversationTurns(sid));
    const preview = result.current.items[0].preview;
    expect(preview.length).toBeLessThanOrEqual(TURN_PREVIEW_MAX_CHARS + 1); // + 省略号
    expect(preview).not.toContain('\n');
  });

  it('filters by session', () => {
    const now = Date.now();
    useStore.setState({
      messages: [
        { id: 'x1', session_id: 'other', role: 'user', content: '别的会话', created_at: now } as never,
      ],
      currentSessionId: sid,
    });
    const { result } = renderHook(() => useConversationTurns(sid));
    expect(result.current.items).toHaveLength(0);
  });

  it('returns empty for null session', () => {
    const { result } = renderHook(() => useConversationTurns(null));
    expect(result.current.items).toHaveLength(0);
  });
});
