// RV3 (round8): TaskTreeSection 重跑失败任务按钮 —— run 终态且有失败任务时
// 显示，点击触发 onRerunFailed；进行中 / 无失败时隐藏。
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { TaskBoardState } from '../../../../features/send-message/chatStreamStore';
import { TaskTreeSection } from '../TaskTreeSection';

vi.mock('../../../../features/manage-settings/useSettings', () => ({
  useSettings: () => ({
    settings: { orch: { runTokenBudget: 10000 } },
    isLoading: false,
    loadSettings: vi.fn(),
    updateSettings: vi.fn(),
    resetSettings: vi.fn(),
  }),
}));

function makeBoard(overrides: Partial<TaskBoardState> = {}): TaskBoardState {
  return {
    runId: 'orch-rerun-ui',
    plan: [
      { task_id: 't1', goal: 'g1', agent_id: 'primary' },
      { task_id: 't2', goal: 'g2', agent_id: 'primary' },
    ] as TaskBoardState['plan'],
    statuses: {
      t1: {
        state: 'task_status',
        run_id: 'orch-rerun-ui',
        task_id: 't1',
        status: 'done',
        agent_id: 'primary',
        goal: 'g1',
        error: null,
        output_preview: null,
        retry_count: 0,
      },
      t2: {
        state: 'task_status',
        run_id: 'orch-rerun-ui',
        task_id: 't2',
        status: 'failed',
        agent_id: 'primary',
        goal: 'g2',
        error: 'boom',
        output_preview: null,
        retry_count: 0,
      },
    } as TaskBoardState['statuses'],
    progress: { total: 2, done: 1, running: 0, queued: 0, failed: 1, cancelled: 0 },
    dispatchedAt: Date.now(),
    ...overrides,
  };
}

describe('TaskTreeSection — rerun failed button (RV3)', () => {
  it('shows rerun button when run terminal and has failures; click fires callback', () => {
    const onRerunFailed = vi.fn();
    render(<TaskTreeSection board={makeBoard()} onRerunFailed={onRerunFailed} />);
    const btn = screen.getByTestId('task-tree-rerun-failed');
    fireEvent.click(btn);
    expect(onRerunFailed).toHaveBeenCalledTimes(1);
  });

  it('hides rerun button while tasks are still in flight', () => {
    const onRerunFailed = vi.fn();
    render(
      <TaskTreeSection
        board={makeBoard({
          progress: { total: 2, done: 1, running: 1, queued: 0, failed: 0, cancelled: 0 },
        })}
        onRerunFailed={onRerunFailed}
      />,
    );
    expect(screen.queryByTestId('task-tree-rerun-failed')).toBeNull();
  });

  it('hides rerun button when no failures', () => {
    render(
      <TaskTreeSection
        board={makeBoard({
          statuses: {
            t1: {
              state: 'task_status',
              run_id: 'orch-rerun-ui',
              task_id: 't1',
              status: 'done',
              agent_id: 'primary',
              goal: 'g1',
              error: null,
              output_preview: null,
              retry_count: 0,
            },
            t2: {
              state: 'task_status',
              run_id: 'orch-rerun-ui',
              task_id: 't2',
              status: 'done',
              agent_id: 'primary',
              goal: 'g2',
              error: null,
              output_preview: null,
              retry_count: 0,
            },
          } as TaskBoardState['statuses'],
          progress: { total: 2, done: 2, running: 0, queued: 0, failed: 0, cancelled: 0 },
        })}
      />,
    );
    expect(screen.queryByTestId('task-tree-rerun-failed')).toBeNull();
  });
});

// ============================================================================
// RD13+ (round15): 重派徽章 —— retry_of 重派任务可追溯
// ============================================================================

describe('TaskTreeSection — 重派徽章 (RD13+)', () => {
  it('retry_of 任务显示"重派"徽章', () => {
    render(
      <TaskTreeSection
        board={makeBoard({
          statuses: {
            t1: {
              state: 'task_status',
              run_id: 'orch-rerun-ui',
              task_id: 't1',
              status: 'done',
              agent_id: 'primary',
              goal: 'g1',
              error: null,
              output_preview: null,
              retry_count: 0,
              retry_of: 't0',
            },
          } as TaskBoardState['statuses'],
          progress: { total: 1, done: 1, running: 0, queued: 0, failed: 0, cancelled: 0 },
        })}
      />,
    );
    expect(screen.getByTestId('task-tree-redeploy-t1')).toBeInTheDocument();
  });

  it('普通任务不显示重派徽章', () => {
    render(<TaskTreeSection board={makeBoard()} />);
    expect(screen.queryByTestId('task-tree-redeploy-t1')).toBeNull();
  });
});

// ============================================================================
// BU9 (round20) → BU13 (round24): 进度行展示消耗
// round24 起 used_tokens 为 per-task 归因值，进度行改为求和且不再依赖预算开关。
// ============================================================================

describe('TaskTreeSection — 消耗可见性 (BU13)', () => {
  it('终态任务 used_tokens 求和展示（per-task 语义）', () => {
    render(
      <TaskTreeSection
        board={makeBoard({
          statuses: {
            t1: {
              state: 'task_status',
              run_id: 'orch-rerun-ui',
              task_id: 't1',
              status: 'done',
              agent_id: 'primary',
              goal: 'g1',
              error: null,
              output_preview: null,
              retry_count: 0,
              used_tokens: 4200,
            },
            t2: {
              state: 'task_status',
              run_id: 'orch-rerun-ui',
              task_id: 't2',
              status: 'failed',
              agent_id: 'primary',
              goal: 'g2',
              error: 'boom',
              output_preview: null,
              retry_count: 0,
              used_tokens: 3800,
            },
          } as TaskBoardState['statuses'],
          progress: { total: 2, done: 1, running: 0, queued: 0, failed: 1, cancelled: 0 },
        })}
      />,
    );
    expect(screen.getByText(/已消耗/)).toBeInTheDocument();
    // 求和 4200+3800=8000；剥掉 locale 分隔符后断言数字本身（ICU 无关）。
    const text = screen.getByText(/已消耗/).textContent ?? '';
    expect(text.replace(/[^0-9]/g, '')).toContain('8000');
  });

  it('预算关闭（orch 缺失）→ 有消耗仍展示（BU13 门槛解除）', () => {
    render(
      <TaskTreeSection
        board={makeBoard({
          statuses: {
            t1: {
              state: 'task_status',
              run_id: 'orch-rerun-ui',
              task_id: 't1',
              status: 'done',
              agent_id: 'primary',
              goal: 'g1',
              error: null,
              output_preview: null,
              retry_count: 0,
              used_tokens: 500,
            },
            t2: {
              state: 'task_status',
              run_id: 'orch-rerun-ui',
              task_id: 't2',
              status: 'failed',
              agent_id: 'primary',
              goal: 'g2',
              error: 'boom',
              output_preview: null,
              retry_count: 0,
            },
          } as TaskBoardState['statuses'],
        })}
      />,
    );
    expect(screen.getByText(/已消耗/)).toBeInTheDocument();
  });

  it('无 used_tokens 数据 → 不显示消耗', () => {
    render(
      <TaskTreeSection
        board={makeBoard({
          statuses: {
            t1: {
              state: 'task_status',
              run_id: 'orch-rerun-ui',
              task_id: 't1',
              status: 'done',
              agent_id: 'primary',
              goal: 'g1',
              error: null,
              output_preview: null,
              retry_count: 0,
            },
            t2: {
              state: 'task_status',
              run_id: 'orch-rerun-ui',
              task_id: 't2',
              status: 'failed',
              agent_id: 'primary',
              goal: 'g2',
              error: 'boom',
              output_preview: null,
              retry_count: 0,
            },
          } as TaskBoardState['statuses'],
        })}
      />,
    );
    expect(screen.queryByText(/已消耗/)).toBeNull();
  });
});

// ============================================================================
// BU13 (round24): 终态任务行内 消耗/耗时 徽章
// ============================================================================

describe('TaskTreeSection — 任务行 usage 徽章 (BU13)', () => {
  it('done 任务带 used_tokens + duration_ms → 行内徽章展示', () => {
    render(
      <TaskTreeSection
        board={makeBoard({
          statuses: {
            t1: {
              state: 'task_status',
              run_id: 'orch-rerun-ui',
              task_id: 't1',
              status: 'done',
              agent_id: 'primary',
              goal: 'g1',
              error: null,
              output_preview: null,
              retry_count: 0,
              used_tokens: 1500,
              duration_ms: 2500,
            },
            t2: {
              state: 'task_status',
              run_id: 'orch-rerun-ui',
              task_id: 't2',
              status: 'done',
              agent_id: 'primary',
              goal: 'g2',
              error: null,
              output_preview: null,
              retry_count: 0,
            },
          } as TaskBoardState['statuses'],
        })}
      />,
    );
    const badge = screen.getByTestId('task-tree-usage-t1');
    expect(badge.textContent).toContain('1.5k tokens');
    expect(badge.textContent).toContain('2.5s');
    expect(screen.queryByTestId('task-tree-usage-t2')).toBeNull();
  });

  it('亚秒时长与整千 token 的格式化边界', () => {
    render(
      <TaskTreeSection
        board={makeBoard({
          statuses: {
            t1: {
              state: 'task_status',
              run_id: 'orch-rerun-ui',
              task_id: 't1',
              status: 'failed',
              agent_id: 'primary',
              goal: 'g1',
              error: 'boom',
              output_preview: null,
              retry_count: 0,
              used_tokens: 1000,
              duration_ms: 450,
            },
            t2: {
              state: 'task_status',
              run_id: 'orch-rerun-ui',
              task_id: 't2',
              status: 'done',
              agent_id: 'primary',
              goal: 'g2',
              error: null,
              output_preview: null,
              retry_count: 0,
              duration_ms: 1000,
            },
          } as TaskBoardState['statuses'],
        })}
      />,
    );
    expect(screen.getByTestId('task-tree-usage-t1').textContent).toContain('450ms');
    expect(screen.getByTestId('task-tree-usage-t2').textContent).toContain('1s');
  });
});

// ============================================================================
// RV4 (round27): 单任务重试按钮
// ============================================================================

describe('TaskTreeSection — 单任务重试 (RV4)', () => {
  it('failed 行渲染重试按钮，点击回调 (runId, taskId)；进行中不渲染', () => {
    const onRetryTask = vi.fn();
    // 终态：全部任务终态 → allDone
    render(
      <TaskTreeSection
        board={makeBoard({
          statuses: {
            t1: {
              state: 'task_status',
              run_id: 'orch-rerun-ui',
              task_id: 't1',
              status: 'done',
              agent_id: 'primary',
              goal: 'g1',
              error: null,
              output_preview: null,
              retry_count: 0,
            },
            t2: {
              state: 'task_status',
              run_id: 'orch-rerun-ui',
              task_id: 't2',
              status: 'failed',
              agent_id: 'primary',
              goal: 'g2',
              error: 'boom',
              output_preview: null,
              retry_count: 0,
            },
          } as TaskBoardState['statuses'],
          progress: { total: 2, done: 1, running: 0, queued: 0, failed: 1, cancelled: 0 },
        })}
      />,
    );
    expect(screen.queryByTestId('task-tree-retry-t2')).toBeNull(); // 未传回调
    cleanup();

    render(
      <TaskTreeSection
        onRetryTask={onRetryTask}
        board={makeBoard({
          statuses: {
            t1: {
              state: 'task_status',
              run_id: 'orch-rerun-ui',
              task_id: 't1',
              status: 'done',
              agent_id: 'primary',
              goal: 'g1',
              error: null,
              output_preview: null,
              retry_count: 0,
            },
            t2: {
              state: 'task_status',
              run_id: 'orch-rerun-ui',
              task_id: 't2',
              status: 'failed',
              agent_id: 'primary',
              goal: 'g2',
              error: 'boom',
              output_preview: null,
              retry_count: 0,
            },
          } as TaskBoardState['statuses'],
          progress: { total: 2, done: 1, running: 0, queued: 0, failed: 1, cancelled: 0 },
        })}
      />,
    );
    const btn = screen.getByTestId('task-tree-retry-t2');
    fireEvent.click(btn);
    expect(onRetryTask).toHaveBeenCalledWith('orch-rerun-ui', 't2');
  });

  it('run 进行中（inFlight>0）不渲染重试按钮', () => {
    render(
      <TaskTreeSection
        onRetryTask={vi.fn()}
        board={makeBoard({
          statuses: {
            t1: {
              state: 'task_status',
              run_id: 'orch-rerun-ui',
              task_id: 't1',
              status: 'done',
              agent_id: 'primary',
              goal: 'g1',
              error: null,
              output_preview: null,
              retry_count: 0,
            },
            t2: {
              state: 'task_status',
              run_id: 'orch-rerun-ui',
              task_id: 't2',
              status: 'failed',
              agent_id: 'primary',
              goal: 'g2',
              error: 'boom',
              output_preview: null,
              retry_count: 0,
            },
            t3: {
              state: 'task_status',
              run_id: 'orch-rerun-ui',
              task_id: 't3',
              status: 'running',
              agent_id: 'primary',
              goal: 'g3',
              error: null,
              output_preview: null,
              retry_count: 0,
            },
          } as TaskBoardState['statuses'],
          progress: { total: 3, done: 1, running: 1, queued: 0, failed: 1, cancelled: 0 },
        })}
      />,
    );
    expect(screen.queryByTestId('task-tree-retry-t2')).toBeNull();
  });
});
