// src/widgets/chat/__tests__/ProgressSection.test.tsx
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';

// C3 (2026-08-15): taskBoard==null 三态渲染 PlanCardList（历史编排记录），
// 挂载即调 orchRunClient.listRuns()；mock 掉避免真实 IPC 抛错。
vi.mock('../../../shared/api/orchRunClient', () => ({
  orchRunClient: { listRuns: vi.fn().mockResolvedValue([]) },
}));

import type { TaskBoard } from '../../../features/send-message/useChat';
import { ProgressSection } from '../progress/ProgressSection';

describe('ProgressSection', () => {
  it('shows iteration when > 0', () => {
    render(<ProgressSection iteration={3} streamingState="thinking" toolCalls={[]} isLoading />);
    expect(screen.getByText(/第 3 轮/)).toBeInTheDocument();
  });

  it('hides iteration when 0', () => {
    render(
      <ProgressSection iteration={0} streamingState={null} toolCalls={[]} isLoading={false} />,
    );
    expect(screen.queryByText(/第 \d+ 轮/)).not.toBeInTheDocument();
  });

  it('shows thinking label while loading', () => {
    render(<ProgressSection iteration={0} streamingState="thinking" toolCalls={[]} isLoading />);
    expect(screen.getByText(/思考中/)).toBeInTheDocument();
  });

  it('shows idle state when not loading', () => {
    render(
      <ProgressSection iteration={0} streamingState={null} toolCalls={[]} isLoading={false} />,
    );
    expect(screen.getByText(/等待输入/)).toBeInTheDocument();
  });

  it('renders tool call names', () => {
    const toolCalls = [
      { id: 'tc1', name: 'write_file', args: {} },
      { id: 'tc2', name: 'search', args: {} },
    ];
    render(
      <ProgressSection iteration={1} streamingState="tool_call" toolCalls={toolCalls} isLoading />,
    );
    expect(screen.getByText('write_file')).toBeInTheDocument();
    expect(screen.getByText('search')).toBeInTheDocument();
  });

  // 进度可视化 P0-2 (2026-08-12): 编排进行中不显示"等待输入",展示 task-progress-summary。
  // C3 (2026-08-15): dispatchedAt 补位 —— 三态后未派发走 PlanCard 分支,摘要仅已派发显示,
  // 原测试语义（"编排进行中"）本就 = 已派发。
  it('shows progress summary when taskBoard with progress present', () => {
    const taskBoard: TaskBoard = {
      runId: 'orch-1',
      plan: [
        { task_id: 't1', agent_id: 'researcher', goal: '搜集资料' },
        { task_id: 't2', agent_id: 'writer', goal: '整理学习资料' },
      ],
      statuses: {},
      progress: { total: 4, done: 1, running: 2, queued: 1, failed: 0, cancelled: 0 },
      dispatchedAt: Date.now(),
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
      progress: { total: 3, done: 1, running: 0, queued: 1, failed: 1, cancelled: 0 },
      dispatchedAt: Date.now(),
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

  it('shows cancelled count for cancelled-only and mixed boards', () => {
    const taskBoard: TaskBoard = {
      runId: 'orch-cancelled',
      plan: [],
      statuses: {},
      progress: { total: 2, done: 1, running: 0, queued: 0, failed: 0, cancelled: 1 },
      dispatchedAt: Date.now(),
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
    expect(screen.getByTestId('task-progress-summary')).toHaveTextContent('(1 已取消)');
  });

  it('taskBoard == null → 渲染 PlanCardList（历史记录）', () => {
    render(
      <ProgressSection
        iteration={0}
        streamingState={null}
        toolCalls={[]}
        isLoading={false}
        taskBoard={null}
        onResumeRun={vi.fn()}
      />,
    );
    expect(screen.getByTestId('plan-card-list')).toBeInTheDocument();
  });

  it('taskBoard 未派发 → 渲染 PlanCard（可编辑）', () => {
    const board: TaskBoard = {
      runId: 'r1',
      plan: [{ task_id: 't1', agent_id: 'researcher', goal: 'G' }],
      statuses: {},
      dispatchedAt: null,
    };
    render(
      <ProgressSection
        iteration={0}
        streamingState={null}
        toolCalls={[]}
        isLoading={false}
        taskBoard={board}
        onResumeRun={vi.fn()}
      />,
    );
    expect(screen.getByTestId('plan-card')).toBeInTheDocument();
  });

  it('taskBoard 已派发 → 渲染 TaskTreeSection', () => {
    const board: TaskBoard = {
      runId: 'r1',
      plan: [{ task_id: 't1', agent_id: 'researcher', goal: 'G' }],
      statuses: {},
      dispatchedAt: Date.now(),
    };
    render(
      <ProgressSection
        iteration={0}
        streamingState={null}
        toolCalls={[]}
        isLoading={false}
        taskBoard={board}
        onResumeRun={vi.fn()}
      />,
    );
    expect(screen.getByTestId('task-tree')).toBeInTheDocument();
  });

  // Wave 3 C4+H1 (2026-08-15): 取消统一委托 onCancelExecution(runId)
  it('taskBoard 未派发：取消 → onCancelExecution(runId)', () => {
    const onCancelExecution = vi.fn();
    const board: TaskBoard = {
      runId: 'r1',
      plan: [{ task_id: 't1', agent_id: 'researcher', goal: 'G' }],
      statuses: {},
      dispatchedAt: null,
    };
    render(
      <ProgressSection
        iteration={0}
        streamingState={null}
        toolCalls={[]}
        isLoading={false}
        taskBoard={board}
        onResumeRun={vi.fn()}
        onCancelExecution={onCancelExecution}
      />,
    );
    fireEvent.click(screen.getByTestId('plan-cancel'));
    expect(onCancelExecution).toHaveBeenCalledWith('r1');
  });

  it('taskBoard 已派发：task-tree 取消按钮 → onCancelExecution(runId)', () => {
    const onCancelExecution = vi.fn();
    const board: TaskBoard = {
      runId: 'r1',
      plan: [{ task_id: 't1', agent_id: 'researcher', goal: 'G' }],
      statuses: {},
      dispatchedAt: Date.now(),
    };
    render(
      <ProgressSection
        iteration={0}
        streamingState={null}
        toolCalls={[]}
        isLoading={false}
        taskBoard={board}
        onResumeRun={vi.fn()}
        onCancelExecution={onCancelExecution}
      />,
    );
    fireEvent.click(screen.getByTestId('task-tree-cancel'));
    expect(onCancelExecution).toHaveBeenCalledWith('r1');
  });
});
