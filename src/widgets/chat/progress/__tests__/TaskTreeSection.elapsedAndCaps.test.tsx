// RV3 (round8): TaskTreeSection 重跑失败任务按钮 —— run 终态且有失败任务时
// 显示，点击触发 onRerunFailed；进行中 / 无失败时隐藏。
import { cleanup, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { TaskBoardState } from '../../../../features/send-message/chatStreamStore';
import { TaskTreeSection } from '../TaskTreeSection';

const useSettingsMock = vi.hoisted(() => vi.fn());

vi.mock('../../../../features/manage-settings/useSettings', () => ({
  useSettings: useSettingsMock,
}));

useSettingsMock.mockReturnValue({
  settings: { orch: { runTokenBudget: 10000 } },
  isLoading: false,
  loadSettings: vi.fn(),
  updateSettings: vi.fn(),
  resetSettings: vi.fn(),
});

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

describe('TaskTreeSection — running 实时耗时 (BU15)', () => {
  it('running 行渲染 elapsed 徽章，done 后消失', () => {
    vi.useFakeTimers();
    try {
      vi.setSystemTime(new Date('2026-09-18T12:00:30Z'));
      const runningSince = Date.now() - 83_000; // 1m23s
      render(
        <TaskTreeSection
          board={makeBoard({
            statuses: {
              t1: {
                state: 'task_status',
                run_id: 'orch-rerun-ui',
                task_id: 't1',
                status: 'running',
                agent_id: 'primary',
                goal: 'g1',
                error: null,
                output_preview: null,
                retry_count: 0,
                runningSince,
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
      expect(screen.getByTestId('task-tree-elapsed-t1').textContent).toBe('1m23s');

      // 终态替换：徽章消失
      cleanup();
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
                duration_ms: 90_000,
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
      expect(screen.queryByTestId('task-tree-elapsed-t1')).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it('亚分钟显示秒；无 runningSince 的 running 行不显示徽章', () => {
    vi.useFakeTimers();
    try {
      vi.setSystemTime(new Date('2026-09-18T12:00:10Z'));
      render(
        <TaskTreeSection
          board={makeBoard({
            statuses: {
              t1: {
                state: 'task_status',
                run_id: 'orch-rerun-ui',
                task_id: 't1',
                status: 'running',
                agent_id: 'primary',
                goal: 'g1',
                error: null,
                output_preview: null,
                retry_count: 0,
                runningSince: Date.now() - 42_000,
              },
              t2: {
                state: 'task_status',
                run_id: 'orch-rerun-ui',
                task_id: 't2',
                status: 'running',
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
      expect(screen.getByTestId('task-tree-elapsed-t1').textContent).toBe('42s');
      expect(screen.queryByTestId('task-tree-elapsed-t2')).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });
});

// ============================================================================
// RD18 (round33): 级联跳过根因徽章
// ============================================================================

describe('TaskTreeSection — 级联跳过根因 (RD18)', () => {
  it('blocked_by_failed 前缀 → 行内根因徽章（多根因顿号连接）', () => {
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
              error: 'blocked_by_failed:t0,t9',
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
              error: '普通失败：boom',
              output_preview: null,
              retry_count: 0,
            },
          } as TaskBoardState['statuses'],
        })}
      />,
    );
    const badge = screen.getByTestId('task-tree-blocked-t1');
    expect(badge.textContent).toBe('因 t0、t9 失败级联跳过');
    expect(screen.queryByTestId('task-tree-blocked-t2')).toBeNull();
  });
});

// ============================================================================
// RD21 (round42): run 触顶原因横幅
// ============================================================================

describe('TaskTreeSection — run 触顶原因横幅 (RD21)', () => {
  it('budget_exceeded 前缀 → 渲染预算触顶横幅（优先）', () => {
    render(
      <TaskTreeSection
        board={makeBoard({
          statuses: {
            t1: {
              state: 'task_status',
              run_id: 'orch-rerun-ui',
              task_id: 't1',
              status: 'cancelled',
              agent_id: 'primary',
              goal: 'g1',
              error: 'budget_exceeded: 本 run token 预算（1000）已耗尽',
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
              error: 'wall_clock_exceeded: 本 run 墙钟上限（30 分钟）已到',
              output_preview: null,
              retry_count: 0,
            },
          } as TaskBoardState['statuses'],
        })}
      />,
    );
    const banner = screen.getByTestId('task-tree-trip-reason');
    expect(banner.textContent).toContain('预算已触顶');
  });

  it('wall_clock_exceeded 前缀 → 渲染墙钟横幅；普通失败不渲染', () => {
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
              error: 'wall_clock_exceeded: 本 run 墙钟上限（30 分钟）已到',
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
    expect(screen.getByTestId('task-tree-trip-reason').textContent).toContain('墙钟上限已到');
    // 普通失败（无守门前缀）不触发横幅
    cleanup();
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
              error: '普通失败：boom',
              output_preview: null,
              retry_count: 0,
            },
          } as TaskBoardState['statuses'],
        })}
      />,
    );
    expect(screen.queryByTestId('task-tree-trip-reason')).toBeNull();
  });
});
