// src/widgets/chat/__tests__/TaskTreeSection.test.tsx
// 2026-11-02 进度面板优化: run 级汇总（完成数 / 进行中 / 失败 / 已取消）、
// 取消按钮、run 级耗时已上移到 StatusBar 常驻顶栏；结果预览与依赖关系
// 已下移到 TaskDetailView。对应断言迁至 StatusBar.test.tsx / TaskDetailView.test.tsx。
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { TaskBoard } from '../../../features/send-message/useChat';
import { TaskTreeSection } from '../progress/TaskTreeSection';

function makeBoard(overrides: Partial<TaskBoard> = {}): TaskBoard {
  return {
    runId: 'orch-1',
    plan: [
      { task_id: 't1', agent_id: 'researcher', goal: '搜集资料' },
      { task_id: 't2', agent_id: 'writer', goal: '整理学习资料' },
    ],
    statuses: {},
    ...overrides,
  };
}

describe('TaskTreeSection', () => {
  it('renders plan rows with agent badges and goals', () => {
    render(<TaskTreeSection board={makeBoard()} />);
    expect(screen.getByText('researcher')).toBeInTheDocument();
    expect(screen.getByText('writer')).toBeInTheDocument();
    expect(screen.getByText('搜集资料')).toBeInTheDocument();
    expect(screen.getByText('整理学习资料')).toBeInTheDocument();
  });

  it('renders running spinner for in-flight task', () => {
    const board = makeBoard({
      statuses: {
        t1: {
          state: 'task_status',
          run_id: 'orch-1',
          task_id: 't1',
          status: 'running',
          agent_id: 'researcher',
          goal: '搜集资料',
          error: null,
          output_preview: null,
        },
      },
    });
    render(<TaskTreeSection board={board} />);
    expect(screen.getByTitle('running')).toBeInTheDocument();
  });

  it('plan row without status falls back to queued', () => {
    render(<TaskTreeSection board={makeBoard()} />);
    expect(screen.getAllByTitle('queued')).toHaveLength(2);
  });

  // 2026-11-02 进度面板优化: 行点击 → 整面板切到 TaskDetailView。
  it('点击任务行触发 onSelectTask(taskId)', () => {
    const onSelectTask = vi.fn();
    render(<TaskTreeSection board={makeBoard()} onSelectTask={onSelectTask} />);
    fireEvent.click(screen.getByTestId('task-tree-item-t1'));
    expect(onSelectTask).toHaveBeenCalledWith('t1');
  });

  it('未提供 onSelectTask 时行不可点击', () => {
    render(<TaskTreeSection board={makeBoard()} />);
    expect(screen.getByTestId('task-tree-item-t1')).not.toHaveAttribute('role', 'button');
  });

  it('renders cancelled status icon for cancelled tasks', () => {
    const board = makeBoard({
      statuses: {
        t1: {
          state: 'task_status',
          run_id: 'orch-1',
          task_id: 't1',
          status: 'cancelled',
          agent_id: 'researcher',
          goal: '搜集资料',
          error: 'cancelled by user',
          output_preview: null,
        },
      },
    });
    render(<TaskTreeSection board={board} />);
    expect(screen.getByTestId('task-tree-item-t1')).toHaveTextContent('⊘');
  });

  // P0-6 (2026-08-20): reviewer 复核结论横幅 —— pass/fail 双色展示
  it('shows review pass banner with assertion count', () => {
    const board = makeBoard({
      review: {
        state: 'task_review',
        run_id: 'orch-1',
        task_id: 't1',
        reviewer_id: 'reviewer',
        verdict: 'pass',
        assertion_count: 4,
        summary: '全部通过',
      },
    });
    render(<TaskTreeSection board={board} />);
    const banner = screen.getByTestId('task-review-banner');
    expect(banner).toHaveTextContent('复核通过');
    expect(banner).toHaveTextContent('4');
  });

  it('shows review fail banner with summary', () => {
    const board = makeBoard({
      review: {
        state: 'task_review',
        run_id: 'orch-1',
        task_id: 't1',
        reviewer_id: 'reviewer',
        verdict: 'fail',
        assertion_count: 3,
        summary: '结论缺少数据支撑',
      },
    });
    render(<TaskTreeSection board={board} />);
    const banner = screen.getByTestId('task-review-banner');
    expect(banner).toHaveTextContent('复核存疑');
    expect(banner).toHaveTextContent('结论缺少数据支撑');
  });

  // P0-7 (2026-08-20): retry_count 徽章 —— 后端一直携带 retry_count, 前端类型此前
  // 未声明被静默丢弃, 现在展示"已重试 ×N"让用户感知到重试发生过。
  it('shows retry badge when task has been retried', () => {
    const board = makeBoard({
      statuses: {
        t1: {
          state: 'task_status',
          run_id: 'orch-1',
          task_id: 't1',
          status: 'done',
          agent_id: 'researcher',
          goal: '搜集资料',
          error: null,
          output_preview: '完成',
          retry_count: 2,
        },
      },
    });
    render(<TaskTreeSection board={board} />);
    expect(screen.getByTestId('task-tree-retry-t1')).toHaveTextContent('已重试 ×2');
  });

  it('hides retry badge when retry_count is zero or absent', () => {
    render(<TaskTreeSection board={makeBoard()} />);
    expect(screen.queryByTestId('task-tree-retry-t1')).not.toBeInTheDocument();
    expect(screen.queryByTestId('task-tree-retry-t2')).not.toBeInTheDocument();
  });

  // RP1 (round34, 2026-09-19): LLM 动态调整计划的"已调整"徽章 —— conductor
  // 在 run 中改过目标 / 新增 / 取消过的任务，用户可追溯偏离初始计划的部分。
  it('shows adjusted badge for tasks whose plan was changed by the LLM', () => {
    const board = makeBoard({
      statuses: {
        t1: {
          state: 'task_status',
          run_id: 'orch-1',
          task_id: 't1',
          status: 'done',
          agent_id: 'researcher',
          goal: '改后的目标',
          error: null,
          output_preview: '完成',
          adjusted: true,
        },
      },
    });
    render(<TaskTreeSection board={board} />);
    expect(screen.getByTestId('task-tree-adjusted-t1')).toHaveTextContent('已调整');
    // 未被调整的任务不显示徽章。
    expect(screen.queryByTestId('task-tree-adjusted-t2')).not.toBeInTheDocument();
  });
});
