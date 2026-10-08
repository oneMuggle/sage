// src/features/chat/__tests__/useConversationTrajectory.test.ts
//
// 对标 F3（ZCode ModelTrajectoryPane）：模型轨迹数据源单测。
// 覆盖: 全角色条目派生、topic_separator 排除、tool_calls wire 字符串解析、
// 预览截断、generation_stats 透传、跨会话过滤、null 会话空态。

import { renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';

import { useStore } from '../../../shared/lib/store';
import type { Session } from '../../../shared/lib/store';
import {
  TRAJECTORY_PREVIEW_MAX_CHARS,
  useConversationTrajectory,
} from '../useConversationTrajectory';

const sid = 's-traj';

function seedMessages(
  msgs: Array<{
    id: string;
    role: 'user' | 'assistant' | 'tool' | 'system';
    content: string;
    subtype?: string | null;
    tool_calls?: string;
    model?: string;
    reasoning_content?: string | null;
    generation_stats?: { input_tokens?: number; output_tokens?: number; latency_ms?: number };
    finish_reason?: string | null;
  }>,
): void {
  const now = Date.now();
  useStore.setState({
    sessions: [
      {
        id: sid,
        title: 'T',
        created_at: now,
        updated_at: now,
        last_message_at: null,
        message_count: msgs.length,
        is_pinned: false,
      } as Session,
    ],
    messages: msgs.map((m, i) => ({
      id: m.id,
      session_id: sid,
      role: m.role,
      content: m.content,
      created_at: now + i,
      model: m.model,
      provider: undefined,
      tool_calls: m.tool_calls,
      tool_call_id: undefined,
      reasoning_content: m.reasoning_content,
      step_index: undefined,
      segment_id: 0,
      subtype: m.subtype ?? null,
      activated_skills: undefined,
      compact_info: undefined,
      memory_refs: undefined,
      rag_citations: undefined,
      sources: undefined,
      finish_reason: m.finish_reason,
      generation_stats: m.generation_stats,
    })),
    currentSessionId: sid,
  });
}

describe('useConversationTrajectory', () => {
  beforeEach(() => {
    useStore.setState({ messages: [], sessions: [] });
  });

  it('derives entries for all roles in order', () => {
    seedMessages([
      { id: 'u1', role: 'user', content: '第一问' },
      { id: 'a1', role: 'assistant', content: '回答' },
      { id: 't1', role: 'tool', content: '工具回显' },
    ]);
    const { result } = renderHook(() => useConversationTrajectory(sid));
    expect(result.current.items.map((e) => [e.messageId, e.role])).toEqual([
      ['u1', 'user'],
      ['a1', 'assistant'],
      ['t1', 'tool'],
    ]);
  });

  it('skips topic_separator markers', () => {
    seedMessages([
      { id: 'u1', role: 'user', content: '问' },
      { id: 'm', role: 'user', content: '段切换', subtype: 'topic_separator' },
    ]);
    const { result } = renderHook(() => useConversationTrajectory(sid));
    expect(result.current.items).toHaveLength(1);
    expect(result.current.items[0].messageId).toBe('u1');
  });

  it('parses wire tool_calls JSON string and counts entries', () => {
    const wire = JSON.stringify([{ id: 'tc1', name: 'web_search', args: { q: 'x' } }]);
    seedMessages([{ id: 'a1', role: 'assistant', content: '', tool_calls: wire }]);
    const { result } = renderHook(() => useConversationTrajectory(sid));
    const entry = result.current.items[0];
    expect(entry.toolCallCount).toBe(1);
    expect(entry.toolCalls[0]).toMatchObject({ name: 'web_search' });
    // 空内容时预览回退为工具占位
    expect(entry.preview).toContain('工具调用');
  });

  it('keeps malformed tool_calls wire as zero calls', () => {
    seedMessages([{ id: 'a1', role: 'assistant', content: '正文', tool_calls: 'not-json' }]);
    const { result } = renderHook(() => useConversationTrajectory(sid));
    expect(result.current.items[0].toolCallCount).toBe(0);
  });

  it('folds whitespace and truncates previews at 60 chars', () => {
    const long = 'a'.repeat(80) + '\n\n' + 'b'.repeat(10);
    seedMessages([{ id: 'u1', role: 'user', content: long }]);
    const { result } = renderHook(() => useConversationTrajectory(sid));
    const preview = result.current.items[0].preview;
    expect(preview.length).toBeLessThanOrEqual(TRAJECTORY_PREVIEW_MAX_CHARS + 1);
    expect(preview).not.toContain('\n');
  });

  it('passes through model, finish_reason and generation_stats', () => {
    seedMessages([
      {
        id: 'a1',
        role: 'assistant',
        content: '答',
        model: 'glm-5',
        finish_reason: 'stop',
        generation_stats: { input_tokens: 10, output_tokens: 20, latency_ms: 1500 },
      },
    ]);
    const { result } = renderHook(() => useConversationTrajectory(sid));
    const entry = result.current.items[0];
    expect(entry.model).toBe('glm-5');
    expect(entry.finishReason).toBe('stop');
    expect(entry.totalTokens).toBe(20);
    expect(entry.latencyMs).toBe(1500);
  });

  it('filters by session', () => {
    const now = Date.now();
    useStore.setState({
      messages: [
        { id: 'x1', session_id: 'other', role: 'user', content: '别的会话', created_at: now } as never,
      ],
      currentSessionId: sid,
    });
    const { result } = renderHook(() => useConversationTrajectory(sid));
    expect(result.current.items).toHaveLength(0);
  });

  it('returns empty for null session', () => {
    const { result } = renderHook(() => useConversationTrajectory(null));
    expect(result.current.items).toHaveLength(0);
  });
});
