// @vitest-environment jsdom
/**
 * TaskDetailView 测试 —— 整面板任务详情视图。
 *
 * 替代 SubagentDetailDrawer.stats.test.tsx（2026-11-02 进度面板优化）。
 * 旧抽屉从 runControlStore.runs 解析任务 → 聊天任务板恒 undefined；
 * 新视图直接读 board.plan + board.statuses + board.live[taskId]。
 */
import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { TaskBoard } from '../../../../features/send-message/useChat';
import { orchRunClient } from '../../../../shared/api/orchRunClient';
import type { SubagentLiveState } from '../../../../shared/api/types/chatAndEventTypes';
import { TaskDetailView } from '../TaskDetailView';

vi.mock('../../../../shared/api/orchRunClient', () => ({
  orchRunClient: {
    cancelTask: vi.fn().mockResolvedValue(undefined),
  },
}));

// R114: 有工具名事件时视图会启用插件名单钩子；本套件不测归属后缀
// （见 PluginOwnerSuffix.test.tsx），固定返回 null 避免真实取数。
vi.mock('../../../../shared/lib/hooks/usePluginNames', () => ({
  usePluginNames: () => null,
}));

function buildBoard(overrides?: Partial<TaskBoard>): TaskBoard {
  return {
    runId: 'run-1',
    plan: [{ task_id: 't1', agent_id: 'researcher', goal: '搜集资料' }],
    statuses: {
      t1: {
        state: 'task_status',
        run_id: 'run-1',
        task_id: 't1',
        status: 'running',
        agent_id: 'researcher',
        goal: '搜集资料',
        error: null,
        output_preview: null,
        runningSince: Date.now() - 5000,
      },
    },
    progress: { total: 1, done: 0, running: 1, queued: 0, failed: 0, cancelled: 0 },
    dispatchedAt: Date.now(),
    ...overrides,
  };
}

describe('TaskDetailView', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('渲染头部：agent_id、goal、状态、返回按钮', () => {
    const board = buildBoard();
    const onBack = vi.fn();
    render(<TaskDetailView board={board} taskId="t1" onBack={onBack} />);

    expect(screen.getByTestId('task-detail-view')).toBeInTheDocument();
    expect(screen.getByTestId('task-detail-back')).toBeInTheDocument();
    expect(screen.getByText('researcher')).toBeInTheDocument();
    expect(screen.getByText('搜集资料')).toBeInTheDocument();
    expect(screen.getByTestId('task-detail-status')).toHaveTextContent('执行中');
  });

  it('running 状态显示当前步骤和实时耗时', () => {
    const board = buildBoard({
      live: {
        t1: {
          liveStep: '🔧 read_file config.json',
          waitingApproval: null,
          events: [],
        } as SubagentLiveState,
      },
    });
    render(<TaskDetailView board={board} taskId="t1" onBack={() => {}} />);

    expect(screen.getByTestId('task-detail-current-step')).toHaveTextContent(
      '🔧 read_file config.json',
    );
    expect(screen.getByTestId('task-detail-stats')).toBeInTheDocument();
  });

  it('显示实时事件列表', () => {
    const board = buildBoard({
      live: {
        t1: {
          liveStep: null,
          waitingApproval: null,
          events: [
            {
              state: 'subagent_event',
              run_id: 'run-1',
              task_id: 't1',
              agent_id: 'researcher',
              goal: '搜集资料',
              phase: 'tool_call',
              tool_name: 'read_file',
              args_summary: 'config.json',
              ts: Date.now(),
            },
          ],
        } as SubagentLiveState,
      },
    });
    render(<TaskDetailView board={board} taskId="t1" onBack={() => {}} />);

    const eventsList = screen.getByTestId('task-detail-events');
    expect(eventsList).toBeInTheDocument();
    expect(eventsList).toHaveTextContent('read_file');
  });

  it('无事件时显示空提示', () => {
    const board = buildBoard();
    render(<TaskDetailView board={board} taskId="t1" onBack={() => {}} />);

    expect(screen.getByTestId('task-detail-events-empty')).toHaveTextContent('暂无实时事件');
  });

  it('点击返回按钮触发 onBack', () => {
    const board = buildBoard();
    const onBack = vi.fn();
    render(<TaskDetailView board={board} taskId="t1" onBack={onBack} />);

    fireEvent.click(screen.getByTestId('task-detail-back'));
    expect(onBack).toHaveBeenCalled();
  });

  it('running 状态显示跳过按钮，点击调用 cancelTask', async () => {
    const board = buildBoard();
    render(<TaskDetailView board={board} taskId="t1" onBack={() => {}} />);

    const skipBtn = screen.getByTestId('task-detail-skip');
    expect(skipBtn).toBeInTheDocument();

    fireEvent.click(skipBtn);
    expect(orchRunClient.cancelTask).toHaveBeenCalledWith('run-1', 't1');
  });

  it('failed 状态显示错误和重试按钮', () => {
    const board = buildBoard({
      statuses: {
        t1: {
          state: 'task_status',
          run_id: 'run-1',
          task_id: 't1',
          status: 'failed',
          agent_id: 'researcher',
          goal: '搜集资料',
          error: 'Network timeout',
          output_preview: null,
          used_tokens: 4200,
          duration_ms: 2500,
        },
      },
      progress: { total: 1, done: 0, running: 0, queued: 0, failed: 1, cancelled: 0 },
    });
    const onRetryTask = vi.fn();
    render(
      <TaskDetailView board={board} taskId="t1" onBack={() => {}} onRetryTask={onRetryTask} />,
    );

    expect(screen.getByTestId('task-detail-error')).toHaveTextContent('Network timeout');
    expect(screen.getByTestId('task-detail-stats')).toHaveTextContent('4.2k tokens');
    expect(screen.getByTestId('task-detail-stats')).toHaveTextContent('2.5s');
    expect(screen.getByTestId('task-detail-retry')).toBeInTheDocument();

    fireEvent.click(screen.getByTestId('task-detail-retry'));
    expect(onRetryTask).toHaveBeenCalledWith('run-1', 't1');
  });

  it('done 状态显示结果预览', () => {
    const board = buildBoard({
      statuses: {
        t1: {
          state: 'task_status',
          run_id: 'run-1',
          task_id: 't1',
          status: 'done',
          agent_id: 'researcher',
          goal: '搜集资料',
          error: null,
          output_preview: '找到 3 份文档',
        },
      },
      progress: { total: 1, done: 1, running: 0, queued: 0, failed: 0, cancelled: 0 },
    });
    render(<TaskDetailView board={board} taskId="t1" onBack={() => {}} />);

    expect(screen.getByTestId('task-detail-output')).toHaveTextContent('找到 3 份文档');
  });

  it('渲染依赖关系（depends_on）', () => {
    const board = buildBoard({
      plan: [
        { task_id: 't1', agent_id: 'researcher', goal: '搜集资料' },
        { task_id: 't2', agent_id: 'writer', goal: '整理学习资料', depends_on: ['t1', 't3'] },
      ],
    });
    render(<TaskDetailView board={board} taskId="t2" onBack={() => {}} />);

    expect(screen.getByTestId('task-detail-deps')).toHaveTextContent('↳ 依赖 t1, t3');
  });

  it('无依赖时不渲染依赖行', () => {
    render(<TaskDetailView board={buildBoard()} taskId="t1" onBack={() => {}} />);
    expect(screen.queryByTestId('task-detail-deps')).toBeNull();
  });

  it('渲染重试次数 / 重派 / 已调整徽章', () => {
    const board = buildBoard({
      statuses: {
        t1: {
          state: 'task_status',
          run_id: 'run-1',
          task_id: 't1',
          status: 'done',
          agent_id: 'researcher',
          goal: '搜集资料',
          error: null,
          output_preview: '完成',
          retry_count: 2,
          retry_of: 't0',
          adjusted: true,
        },
      },
      progress: { total: 1, done: 1, running: 0, queued: 0, failed: 0, cancelled: 0 },
    });
    render(<TaskDetailView board={board} taskId="t1" onBack={() => {}} />);

    expect(screen.getByTestId('task-detail-retry-count')).toHaveTextContent('已重试 ×2');
    expect(screen.getByTestId('task-detail-redeploy')).toBeInTheDocument();
    expect(screen.getByTestId('task-detail-adjusted')).toHaveTextContent('已调整');
  });

  it('终态任务不显示跳过/重试按钮', () => {
    const board = buildBoard({
      statuses: {
        t1: {
          state: 'task_status',
          run_id: 'run-1',
          task_id: 't1',
          status: 'done',
          agent_id: 'researcher',
          goal: '搜集资料',
          error: null,
          output_preview: null,
        },
      },
      progress: { total: 1, done: 1, running: 0, queued: 0, failed: 0, cancelled: 0 },
    });
    render(<TaskDetailView board={board} taskId="t1" onBack={() => {}} />);

    expect(screen.queryByTestId('task-detail-skip')).toBeNull();
    expect(screen.queryByTestId('task-detail-retry')).toBeNull();
  });
});
