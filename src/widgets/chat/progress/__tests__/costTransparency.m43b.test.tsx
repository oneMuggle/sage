// @vitest-environment jsdom
/**
 * M4.3b（成本透明）前端展示测试。
 *
 * 覆盖四处金额展示：
 *  1. TaskTreeSection —— 任务行内用量徽章（token · 耗时 · 金额）
 *  2. TaskDetailView —— 任务详情统计行金额
 *  3. StatusBar —— run 级金额合计
 *  4. SessionRunHistory —— 历史 run 行金额合计
 *
 * 语义要点：金额来自内置价格表估算，一律带 "≈"；定价未知（无 used_cost_usd /
 * cost_usd）时**不显示**金额 —— 未知 ≠ 免费，更不能显示 $0。
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { TaskBoard } from '../../../../features/send-message/useChat';
import { orchRunClient } from '../../../../shared/api/orchRunClient';
import { SessionRunHistory } from '../SessionRunHistory';
import { StatusBar } from '../StatusBar';
import { TaskDetailView } from '../TaskDetailView';
import { TaskTreeSection } from '../TaskTreeSection';
import { formatCostUsd } from '../progressFormat';

const useSettingsMock = vi.hoisted(() => vi.fn());
vi.mock('../../../../features/manage-settings/useSettings', () => ({
  useSettings: useSettingsMock,
}));

vi.mock('../../../../shared/api/orchRunClient', () => ({
  orchRunClient: {
    cancelTask: vi.fn().mockResolvedValue(undefined),
    listSessionRuns: vi.fn(),
  },
}));

vi.mock('../../../../shared/api/orchRunControlClient', () => ({
  orchRunControlClient: {
    setApprovalMode: vi.fn().mockResolvedValue({ ok: true }),
    pauseRun: vi.fn().mockResolvedValue({ ok: true, affected: 0 }),
    resumeRun: vi.fn().mockResolvedValue({ ok: true, affected: 0 }),
    pauseTask: vi.fn().mockResolvedValue({ ok: true }),
    resumeTask: vi.fn().mockResolvedValue({ ok: true }),
    followupTask: vi.fn(),
    getTaskTranscript: vi.fn().mockResolvedValue({
      run_id: 'orch-1',
      task_id: 't1',
      messages: [],
      next_seq: 0,
      has_more: false,
    }),
  },
}));

// 插件名单钩子需要真实取数 —— 本套件不测归属后缀，固定返回 null。
vi.mock('../../../../shared/lib/hooks/usePluginNames', () => ({
  usePluginNames: () => null,
}));

useSettingsMock.mockReturnValue({
  settings: { orch: { runWallClockLimitMinutes: 0, runTokenBudget: 10000 } },
  isLoading: false,
  loadSettings: vi.fn(),
  updateSettings: vi.fn(),
  resetSettings: vi.fn(),
});

function makeBoard(overrides: Partial<TaskBoard> = {}): TaskBoard {
  return {
    runId: 'orch-1',
    plan: [{ task_id: 't1', agent_id: 'researcher', goal: '搜集资料' }],
    statuses: {},
    progress: { total: 1, done: 1, running: 0, queued: 0, failed: 0, cancelled: 0 },
    dispatchedAt: Date.now(),
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  useSettingsMock.mockReturnValue({
    settings: { orch: { runWallClockLimitMinutes: 0, runTokenBudget: 10000 } },
    isLoading: false,
    loadSettings: vi.fn(),
    updateSettings: vi.fn(),
    resetSettings: vi.fn(),
  });
});

describe('formatCostUsd', () => {
  it('带 ≈ 前缀并保留 4 位小数', () => {
    expect(formatCostUsd(0.0123)).toBe('≈ $0.0123');
    expect(formatCostUsd(1.5)).toBe('≈ $1.5000');
  });

  it('极小金额折叠为 <$0.0001，避免被读成免费', () => {
    expect(formatCostUsd(0.00005)).toBe('≈<$0.0001');
    expect(formatCostUsd(0)).toBe('≈<$0.0001');
  });
});

describe('TaskTreeSection — 任务级金额徽章', () => {
  it('终态任务展示已定价金额', () => {
    render(
      <TaskTreeSection
        board={makeBoard({
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
              used_cost_usd: 0.0123,
            },
          },
        })}
      />,
    );
    const badge = screen.getByTestId('task-tree-usage-t1');
    expect(badge.textContent).toContain('≈ $0.0123');
  });

  it('金额与 token / 耗时并存时以 · 分隔', () => {
    render(
      <TaskTreeSection
        board={makeBoard({
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
              duration_ms: 1500,
              used_cost_usd: 0.0123,
            },
          },
        })}
      />,
    );
    const badge = screen.getByTestId('task-tree-usage-t1');
    expect(badge.textContent).toContain('4.2k tokens');
    expect(badge.textContent).toContain('1.5s');
    expect(badge.textContent).toContain('≈ $0.0123');
  });

  it('定价未知 → 不显示金额（也不显示 $0）', () => {
    render(
      <TaskTreeSection
        board={makeBoard({
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
        })}
      />,
    );
    expect(screen.queryByTestId('task-tree-usage-t1')).toBeNull();
  });
});

describe('TaskDetailView — 任务详情金额', () => {
  it('展示已定价金额', () => {
    render(
      <TaskDetailView
        board={makeBoard({
          statuses: {
            t1: {
              state: 'task_status',
              run_id: 'orch-1',
              task_id: 't1',
              status: 'done',
              agent_id: 'researcher',
              goal: '搜集资料',
              error: null,
              output_preview: 'ok',
              used_cost_usd: 0.0123,
            },
          },
        })}
        taskId="t1"
        onBack={vi.fn()}
      />,
    );
    const el = screen.getByTestId('task-detail-cost');
    expect(el.textContent).toContain('金额 ≈ $0.0123');
  });

  it('定价未知 → 不渲染金额行', () => {
    render(
      <TaskDetailView
        board={makeBoard({
          statuses: {
            t1: {
              state: 'task_status',
              run_id: 'orch-1',
              task_id: 't1',
              status: 'done',
              agent_id: 'researcher',
              goal: '搜集资料',
              error: null,
              output_preview: 'ok',
            },
          },
        })}
        taskId="t1"
        onBack={vi.fn()}
      />,
    );
    expect(screen.queryByTestId('task-detail-cost')).toBeNull();
  });
});

describe('StatusBar — run 级金额合计', () => {
  it('各任务已定价金额求和', () => {
    render(
      <StatusBar
        streamingState={null}
        isLoading={false}
        iteration={0}
        board={makeBoard({
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
              used_cost_usd: 0.0123,
            },
            t2: {
              state: 'task_status',
              run_id: 'orch-1',
              task_id: 't2',
              status: 'done',
              agent_id: 'writer',
              goal: '整理资料',
              error: null,
              output_preview: null,
              used_cost_usd: 0.0037,
            },
          },
        })}
      />,
    );
    const el = screen.getByTestId('task-run-cost');
    expect(el.textContent).toContain('金额 ≈ $0.0160');
  });

  it('全部定价未知 → 不显示 run 级金额', () => {
    render(
      <StatusBar
        streamingState={null}
        isLoading={false}
        iteration={0}
        board={makeBoard({
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
        })}
      />,
    );
    expect(screen.queryByTestId('task-run-cost')).toBeNull();
  });
});

describe('SessionRunHistory — 历史 run 金额', () => {
  it('展示后端聚合好的 run 级金额', async () => {
    vi.mocked(orchRunClient.listSessionRuns).mockResolvedValue({
      runs: [
        {
          run_id: 'run-1',
          session_id: 'sess-1',
          status: 'completed',
          created_at: Date.now(),
          plan: [],
          original_request: '调研任务',
          // M4.3b: 金额由后端按 run_id 从 usage_events 账本聚合后透出，
          // 前端不再自行对 tasks 求和（tasks 里的 cost_usd 是单任务维度）。
          cost_usd: 0.016,
          tasks: [
            { task_id: 't1', status: 'done', used_tokens: 100, cost_usd: 0.0123 },
            { task_id: 't2', status: 'done', used_tokens: 200, cost_usd: 0.0037 },
          ],
        },
      ],
    });
    render(<SessionRunHistory sessionId="sess-1" onSelectRun={vi.fn()} />);
    fireEvent.click(screen.getByTestId('run-history-toggle'));
    const el = await screen.findByTestId('run-history-cost-run-1');
    expect(el.textContent).toContain('≈ $0.0160');
  });

  it('定价未知（cost_usd 为 null）→ 不显示金额', async () => {
    vi.mocked(orchRunClient.listSessionRuns).mockResolvedValue({
      runs: [
        {
          run_id: 'run-2',
          session_id: 'sess-1',
          status: 'completed',
          created_at: Date.now(),
          plan: [],
          original_request: '未知定价任务',
          cost_usd: null,
          tasks: [{ task_id: 't1', status: 'done', used_tokens: 100, cost_usd: null }],
        },
      ],
    });
    render(<SessionRunHistory sessionId="sess-1" onSelectRun={vi.fn()} />);
    fireEvent.click(screen.getByTestId('run-history-toggle'));
    await waitFor(() => {
      expect(screen.getByTestId('run-history-item-run-2')).toBeInTheDocument();
    });
    expect(screen.queryByTestId('run-history-cost-run-2')).toBeNull();
  });

  it('run 级金额缺失（老数据无该字段）→ 不显示金额，也不显示 $0', async () => {
    vi.mocked(orchRunClient.listSessionRuns).mockResolvedValue({
      runs: [
        {
          run_id: 'run-3',
          session_id: 'sess-1',
          status: 'completed',
          created_at: Date.now(),
          plan: [],
          original_request: '旧 run（无金额字段）',
          tasks: [{ task_id: 't1', status: 'done', used_tokens: 100 }],
        },
      ],
    });
    render(<SessionRunHistory sessionId="sess-1" onSelectRun={vi.fn()} />);
    fireEvent.click(screen.getByTestId('run-history-toggle'));
    await waitFor(() => {
      expect(screen.getByTestId('run-history-item-run-3')).toBeInTheDocument();
    });
    expect(screen.queryByTestId('run-history-cost-run-3')).toBeNull();
  });
});
