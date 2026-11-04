// src/widgets/chat/progress/__tests__/StatusBar.test.tsx
/**
 * StatusBar 测试 —— 进度面板常驻顶栏。
 *
 * 2026-11-02 进度面板优化：run 级汇总（完成数 / 进行中 / 失败 / 已取消）、
 * 取消按钮、自动批准开关、run 级耗时从 TaskTreeSection 上移到本组件，
 * 原有断言随之迁移至此。
 */
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { TaskBoard } from '../../../../features/send-message/useChat';
import { StatusBar } from '../StatusBar';

const useSettingsMock = vi.hoisted(() => vi.fn());
vi.mock('../../../../features/manage-settings/useSettings', () => ({
  useSettings: useSettingsMock,
}));

const setApprovalModeMock = vi.hoisted(() => vi.fn());
vi.mock('../../../../shared/api/orchRunControlClient', () => ({
  orchRunControlClient: {
    setApprovalMode: (...args: unknown[]) => setApprovalModeMock(...args),
  },
}));

useSettingsMock.mockReturnValue({
  settings: { orch: { runWallClockLimitMinutes: 0 } },
  isLoading: false,
  loadSettings: vi.fn(),
  updateSettings: vi.fn(),
  resetSettings: vi.fn(),
});

function makeBoard(overrides: Partial<TaskBoard> = {}): TaskBoard {
  return {
    runId: 'orch-1',
    plan: [
      { task_id: 't1', agent_id: 'researcher', goal: '搜集资料' },
      { task_id: 't2', agent_id: 'writer', goal: '整理学习资料' },
    ],
    statuses: {},
    dispatchedAt: Date.now(),
    ...overrides,
  };
}

function renderBar(board: TaskBoard | null, onCancel?: () => void) {
  return render(
    <StatusBar
      streamingState={null}
      isLoading={false}
      iteration={0}
      board={board}
      onCancel={onCancel}
    />,
  );
}

beforeEach(() => {
  useSettingsMock.mockReturnValue({
    settings: { orch: { runWallClockLimitMinutes: 0 } },
    isLoading: false,
    loadSettings: vi.fn(),
    updateSettings: vi.fn(),
    resetSettings: vi.fn(),
  });
  setApprovalModeMock.mockReset();
  setApprovalModeMock.mockResolvedValue({ ok: true, run_id: 'orch-1', mode: 'auto' });
});

describe('StatusBar — run 级汇总', () => {
  it('已派发 → 渲染进度条与完成数 / 进行中数', () => {
    renderBar(
      makeBoard({
        progress: { total: 4, done: 1, running: 2, queued: 1, failed: 0, cancelled: 0 },
      }),
    );
    expect(screen.getByTestId('progress-bar')).toHaveAttribute('aria-valuenow', '1');
    expect(screen.getByTestId('progress-bar')).toHaveAttribute('aria-valuemax', '4');
    expect(screen.getByTestId('task-progress-summary')).toHaveTextContent(/编排任务 1\/4 完成/);
    expect(screen.getByTestId('task-progress-summary')).toHaveTextContent(/3 个进行中/);
  });

  it('失败计数以 (N 失败) 展示', () => {
    renderBar(
      makeBoard({
        progress: { total: 3, done: 1, running: 0, queued: 1, failed: 1, cancelled: 0 },
      }),
    );
    expect(screen.getByTestId('task-progress-summary')).toHaveTextContent(/\(1 失败\)/);
  });

  it('已取消计数展示', () => {
    renderBar(
      makeBoard({
        progress: { total: 2, done: 1, running: 0, queued: 0, failed: 0, cancelled: 1 },
      }),
    );
    expect(screen.getByTestId('task-progress-summary')).toHaveTextContent('(1 已取消)');
  });

  it('汇总各任务 used_tokens 得到 run 级消耗', () => {
    renderBar(
      makeBoard({
        statuses: {
          t1: {
            state: 'task_status',
            run_id: 'orch-1',
            task_id: 't1',
            status: 'done',
            agent_id: 'researcher',
            goal: '搜集资料',
            error: null,
            output_preview: null,
            used_tokens: 4200,
          },
        },
        progress: { total: 1, done: 1, running: 0, queued: 0, failed: 0, cancelled: 0 },
      }),
    );
    expect(screen.getByTestId('progress-status-bar')).toHaveTextContent('消耗 4.2k tokens');
  });

  // BU13 (round24): used_tokens 为 per-task 归因值，run 级消耗 = 各任务求和。
  it('终态任务 used_tokens 求和展示（per-task 语义）', () => {
    renderBar(
      makeBoard({
        statuses: {
          t1: {
            state: 'task_status',
            run_id: 'orch-1',
            task_id: 't1',
            status: 'done',
            agent_id: 'researcher',
            goal: '搜集资料',
            error: null,
            output_preview: null,
            used_tokens: 4200,
          },
          t2: {
            state: 'task_status',
            run_id: 'orch-1',
            task_id: 't2',
            status: 'failed',
            agent_id: 'writer',
            goal: '整理学习资料',
            error: 'boom',
            output_preview: null,
            used_tokens: 3800,
          },
        },
        progress: { total: 2, done: 1, running: 0, queued: 0, failed: 1, cancelled: 0 },
      }),
    );
    // 求和 4200+3800=8000
    expect(screen.getByTestId('progress-status-bar')).toHaveTextContent('消耗 8k tokens');
  });

  it('预算关闭（orch 缺失）→ 有消耗仍展示（BU13 门槛解除）', () => {
    renderBar(
      makeBoard({
        statuses: {
          t1: {
            state: 'task_status',
            run_id: 'orch-1',
            task_id: 't1',
            status: 'done',
            agent_id: 'researcher',
            goal: '搜集资料',
            error: null,
            output_preview: null,
            used_tokens: 500,
          },
        },
        progress: { total: 2, done: 1, running: 0, queued: 0, failed: 1, cancelled: 0 },
      }),
    );
    expect(screen.getByTestId('progress-status-bar')).toHaveTextContent('消耗 500 tokens');
  });

  it('无 used_tokens 数据 → 不显示消耗', () => {
    renderBar(
      makeBoard({
        progress: { total: 2, done: 1, running: 0, queued: 0, failed: 1, cancelled: 0 },
      }),
    );
    expect(screen.getByTestId('progress-status-bar').textContent).not.toContain('消耗');
  });

  it('未派发 → 显示计划待执行标签，无进度条', () => {
    renderBar(makeBoard({ dispatchedAt: null }));
    expect(screen.getByTestId('plan-pending-label')).toBeInTheDocument();
    expect(screen.queryByTestId('progress-bar')).toBeNull();
    expect(screen.queryByTestId('task-progress-summary')).toBeNull();
  });

  it('无编排 board → 显示等待输入', () => {
    renderBar(null);
    expect(screen.getByTestId('progress-status-bar')).toHaveTextContent('等待输入');
  });
});

describe('StatusBar — 取消执行', () => {
  it('已派发且未终态 → 显示取消按钮，点击触发 onCancel', () => {
    const onCancel = vi.fn();
    renderBar(
      makeBoard({
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
        progress: { total: 1, done: 0, running: 1, queued: 0, failed: 0, cancelled: 0 },
      }),
      onCancel,
    );
    expect(screen.getByTestId('task-tree-cancel')).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('task-tree-cancel'));
    expect(onCancel).toHaveBeenCalled();
  });

  it('run 终态 → 隐藏取消按钮', () => {
    renderBar(
      makeBoard({
        statuses: {
          t1: {
            state: 'task_status',
            run_id: 'orch-1',
            task_id: 't1',
            status: 'done',
            agent_id: 'researcher',
            goal: '搜集资料',
            error: null,
            output_preview: null,
          },
        },
        progress: { total: 1, done: 1, running: 0, queued: 0, failed: 0, cancelled: 0 },
      }),
      vi.fn(),
    );
    expect(screen.queryByTestId('task-tree-cancel')).toBeNull();
  });

  it('未提供 onCancel → 隐藏取消按钮', () => {
    renderBar(makeBoard());
    expect(screen.queryByTestId('task-tree-cancel')).toBeNull();
  });
});

describe('StatusBar — 自动批准开关', () => {
  it('点击切换审批模式并调 setApprovalMode', () => {
    renderBar(makeBoard());
    const btn = screen.getByTestId('task-tree-approval-mode');
    expect(btn).toHaveTextContent('自动批准：关');
    fireEvent.click(btn);
    expect(setApprovalModeMock).toHaveBeenCalledWith({ run_id: 'orch-1', mode: 'auto' });
  });
});

describe('StatusBar — run 级耗时', () => {
  it('in-flight 显示已运行与墙钟上限提示', () => {
    vi.useFakeTimers();
    try {
      useSettingsMock.mockReturnValue({
        settings: { orch: { runWallClockLimitMinutes: 30 } },
        isLoading: false,
        loadSettings: vi.fn(),
        updateSettings: vi.fn(),
        resetSettings: vi.fn(),
      });
      vi.setSystemTime(new Date('2026-09-18T12:05:00Z'));
      renderBar(
        makeBoard({
          dispatchedAt: Date.now() - 150_000, // 2m30s
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
          progress: { total: 1, done: 0, running: 1, queued: 0, failed: 0, cancelled: 0 },
        }),
      );
      const el = screen.getByTestId('task-tree-run-elapsed');
      expect(el.textContent).toContain('已运行 2m30s');
      expect(el.textContent).toContain('上限 30 分钟');
    } finally {
      vi.useRealTimers();
    }
  });

  it('未配置墙钟上限时不显示上限提示', () => {
    vi.useFakeTimers();
    try {
      vi.setSystemTime(new Date('2026-09-18T12:05:00Z'));
      renderBar(
        makeBoard({
          dispatchedAt: Date.now() - 90_000,
          progress: { total: 2, done: 1, running: 0, queued: 0, failed: 1, cancelled: 0 },
        }),
      );
      const el = screen.getByTestId('task-tree-run-elapsed');
      expect(el.textContent).toContain('已运行 1m30s');
      expect(el.textContent).not.toContain('上限');
    } finally {
      vi.useRealTimers();
    }
  });

  it('endedAt 存在时冻结为 run 原始总时长', () => {
    vi.useFakeTimers();
    try {
      vi.setSystemTime(new Date('2026-09-18T12:00:00Z'));
      renderBar(
        makeBoard({
          dispatchedAt: Date.now() - 600_000,
          endedAt: Date.now() - 300_000, // run 原始时长 5 分钟
          progress: { total: 1, done: 1, running: 0, queued: 0, failed: 0, cancelled: 0 },
        }),
      );
      expect(screen.getByTestId('task-tree-run-elapsed').textContent).toContain('已运行 5m');
      vi.advanceTimersByTime(60_000);
      expect(screen.getByTestId('task-tree-run-elapsed').textContent).toContain('已运行 5m');
    } finally {
      vi.useRealTimers();
    }
  });
});

describe('StatusBar — 无编排时的状态', () => {
  it('加载中显示当前状态与轮次', () => {
    cleanup();
    render(<StatusBar streamingState="thinking" isLoading iteration={3} board={null} />);
    expect(screen.getByTestId('progress-status-bar')).toHaveTextContent('思考中');
    expect(screen.getByTestId('progress-status-bar')).toHaveTextContent('第 3 轮');
  });
});
