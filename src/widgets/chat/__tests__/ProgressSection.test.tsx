// src/widgets/chat/__tests__/ProgressSection.test.tsx
import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';

import type { TaskBoard } from '../../../features/send-message/useChat';
import { ProgressSection } from '../progress/ProgressSection';

describe('ProgressSection', () => {
  it('shows iteration when > 0', () => {
    render(<ProgressSection iteration={3} streamingState="thinking" toolCalls={[]} isLoading />);
    expect(screen.getByText(/第 3 轮/)).toBeInTheDocument();
  });

  it('hides iteration when 0', () => {
    render(<ProgressSection iteration={0} streamingState={null} toolCalls={[]} isLoading={false} />);
    expect(screen.queryByText(/第 \d+ 轮/)).not.toBeInTheDocument();
  });

  it('shows thinking label while loading', () => {
    render(<ProgressSection iteration={0} streamingState="thinking" toolCalls={[]} isLoading />);
    expect(screen.getByText(/思考中/)).toBeInTheDocument();
  });

  it('shows idle state when not loading and no taskBoard', () => {
    render(<ProgressSection iteration={0} streamingState={null} toolCalls={[]} isLoading={false} />);
    expect(screen.getByText(/等待输入/)).toBeInTheDocument();
  });

  it('renders tool call names', () => {
    const toolCalls = [
      { id: 'tc1', name: 'write_file', args: {} },
      { id: 'tc2', name: 'search', args: {} },
    ];
    render(<ProgressSection iteration={1} streamingState="tool_call" toolCalls={toolCalls} isLoading />);
    expect(screen.getByText('write_file')).toBeInTheDocument();
    expect(screen.getByText('search')).toBeInTheDocument();
  });

  // 进度可视化 P0-2 (2026-08-12): 编排进行中不显示"等待输入",展示 task-progress-summary
  it('shows progress summary when taskBoard with progress present', () => {
    const taskBoard: TaskBoard = {
      runId: 'orch-1',
      plan: [
        { task_id: 't1', agent_id: 'researcher', goal: '搜集资料' },
        { task_id: 't2', agent_id: 'writer', goal: '整理学习资料' },
      ],
      statuses: {},
      progress: { total: 4, done: 1, running: 2, queued: 1, failed: 0 },
    };
    render(
      <ProgressSection
        iteration={0}
        streamingState={null}
        toolCalls={[]}
        isLoading={false}
        taskBoard={taskBoard}
      />,
    );
    // 编排摘要出现（"进行中" = queued + running，与 TaskTreeSection 口径一致）
    expect(screen.getByTestId('task-progress-summary')).toHaveTextContent(/编排任务 1\/4 完成/);
    expect(screen.getByTestId('task-progress-summary')).toHaveTextContent(/3 个进行中/);
    // "等待输入"不出现
    expect(screen.queryByText(/等待输入/)).not.toBeInTheDocument();
  });

  it('shows failed count next to progress summary', () => {
    const taskBoard: TaskBoard = {
      runId: 'orch-1',
      plan: [],
      statuses: {},
      progress: { total: 3, done: 1, running: 0, queued: 1, failed: 1 },
    };
    render(
      <ProgressSection
        iteration={0}
        streamingState={null}
        toolCalls={[]}
        isLoading={false}
        taskBoard={taskBoard}
      />,
    );
    expect(screen.getByTestId('task-progress-summary')).toHaveTextContent(/\(1 失败\)/);
  });
});
