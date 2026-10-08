// src/widgets/chat/__tests__/TrajectoryPane.test.tsx
//
// 对标 F3（ZCode ModelTrajectoryPane）：轨迹面板组件测试。
// 覆盖: 条目渲染（角色徽标+辅助行）、搜索过滤（命中/不命中）、
// 点击展开详情、点击触发 messageJump、空态与无命中态。

import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi, beforeEach } from 'vitest';

const { jumpSpy } = vi.hoisted(() => ({ jumpSpy: vi.fn() }));

vi.mock('../../../features/chat/messageJumpStore', () => ({
  requestMessageJump: jumpSpy,
}));

import { useStore } from '../../../shared/lib/store';
import type { Session } from '../../../shared/lib/store';
import { TrajectoryPane } from '../TrajectoryPane';

const sid = 's-pane';

interface SeedMsg {
  id: string;
  role: 'user' | 'assistant' | 'tool' | 'system';
  content: string;
  model?: string;
  tool_calls?: string;
  reasoning_content?: string;
  step_index?: number;
  subtype?: string;
  finish_reason?: string;
  generation_stats?: { input_tokens?: number; output_tokens?: number; latency_ms?: number };
}

function seedMessages(msgs: SeedMsg[]): void {
  const now = 1727600000000;
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
      created_at: now + i * 1000,
      model: m.model,
      provider: undefined,
      tool_calls: m.tool_calls,
      tool_call_id: undefined,
      reasoning_content: m.reasoning_content,
      step_index: m.step_index,
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

describe('TrajectoryPane', () => {
  beforeEach(() => {
    jumpSpy.mockClear();
    useStore.setState({ messages: [], sessions: [] });
  });

  it('renders entries with role badge and meta line', () => {
    seedMessages([
      { id: 'u1', role: 'user', content: '帮我查天气' },
      { id: 'a1', role: 'assistant', content: '好的，正在查询', model: 'glm-5' },
    ]);
    render(<TrajectoryPane sessionId={sid} />);
    expect(screen.getAllByTestId('trajectory-entry')).toHaveLength(2);
    expect(screen.getByText('帮我查天气')).toBeInTheDocument();
    expect(screen.getByText('好的，正在查询')).toBeInTheDocument();
    // meta 行是 join(' · ') 的单文本节点，用正则断言 model 出现
    expect(screen.getByText(/glm-5/)).toBeInTheDocument();
  });

  it('filters by search query across preview and tool names', () => {
    seedMessages([
      { id: 'u1', role: 'user', content: '帮我查天气' },
      {
        id: 'a1',
        role: 'assistant',
        content: '调用工具',
        tool_calls: JSON.stringify([{ id: 'tc1', name: 'web_search', args: {} }]),
      },
    ]);
    render(<TrajectoryPane sessionId={sid} />);
    const box = screen.getByTestId('trajectory-search') as HTMLInputElement;
    // 按内容命中
    fireEvent.change(box, { target: { value: '天气' } });
    expect(screen.getAllByTestId('trajectory-entry')).toHaveLength(1);
    expect(screen.getByText('帮我查天气')).toBeInTheDocument();
    // 按工具名命中
    fireEvent.change(box, { target: { value: 'web_search' } });
    expect(screen.getAllByTestId('trajectory-entry')).toHaveLength(1);
    // 无命中
    fireEvent.change(box, { target: { value: '不存在xyz' } });
    expect(screen.queryByTestId('trajectory-entry')).not.toBeInTheDocument();
    expect(screen.getByText('无匹配轨迹')).toBeInTheDocument();
  });

  it('expands detail with reasoning and tool payload on click, and jumps to message', () => {
    seedMessages([
      {
        id: 'a1',
        role: 'assistant',
        content: '答案',
        reasoning_content: '先想一下再答',
        tool_calls: JSON.stringify([{ id: 'tc1', name: 'web_search', args: { q: '天气' }, result: '晴' }]),
        finish_reason: 'stop',
      },
    ]);
    render(<TrajectoryPane sessionId={sid} />);
    fireEvent.click(screen.getByTestId('trajectory-entry'));
    const detail = screen.getByTestId('trajectory-detail');
    expect(detail).toHaveTextContent('先想一下再答');
    expect(detail).toHaveTextContent('web_search');
    expect(detail).toHaveTextContent('finish: stop');
    expect(jumpSpy).toHaveBeenCalledWith({ messageId: 'a1' });
    // 再点收起
    fireEvent.click(screen.getByTestId('trajectory-entry'));
    expect(screen.queryByTestId('trajectory-detail')).not.toBeInTheDocument();
  });

  it('supports F4 role/tool filter pills, telemetry summary, latency bar, and copy JSON', () => {
    seedMessages([
      { id: 'u1', role: 'user', content: '请调用搜索' },
      {
        id: 'a1',
        role: 'assistant',
        content: '已完成搜索',
        model: 'glm-5',
        tool_calls: JSON.stringify([{ id: 'tc1', name: 'web_search', args: { q: 'sage' } }]),
        generation_stats: { input_tokens: 120, output_tokens: 45, latency_ms: 800 },
      },
    ]);
    render(<TrajectoryPane sessionId={sid} />);
    expect(screen.getByTestId('trajectory-summary')).toHaveTextContent('2 条轨迹');
    expect(screen.getByTestId('trajectory-summary')).toHaveTextContent('Token 120 in / 45 out');
    expect(screen.getByTestId('trajectory-latency-bar')).toBeInTheDocument();

    fireEvent.click(screen.getByTestId('trajectory-filter-tool'));
    expect(screen.getAllByTestId('trajectory-entry')).toHaveLength(1);
    fireEvent.click(screen.getByTestId('trajectory-entry'));
    fireEvent.click(screen.getByTestId('trajectory-copy-json'));
    expect(screen.getByTestId('trajectory-copy-json')).toHaveTextContent('已复制');
  });

  it('renders empty state for session without messages', () => {
    render(<TrajectoryPane sessionId={sid} />);
    expect(screen.getByText('暂无轨迹')).toBeInTheDocument();
    expect(screen.queryByTestId('trajectory-entry')).not.toBeInTheDocument();
  });
});
