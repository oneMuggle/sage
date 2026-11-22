// @vitest-environment jsdom
/**
 * TaskDetailView 测试 —— 整面板任务详情视图。
 *
 * 替代 SubagentDetailDrawer.stats.test.tsx（2026-11-02 进度面板优化）。
 * 旧抽屉从 runControlStore.runs 解析任务 → 聊天任务板恒 undefined；
 * 新视图直接读 board.plan + board.statuses + board.live[taskId]。
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { useRunControlStore } from '../../../../entities/orchestration/runControlStore';
import type { TaskBoard } from '../../../../features/send-message/useChat';
import { orchRunClient } from '../../../../shared/api/orchRunClient';
import { orchRunControlClient } from '../../../../shared/api/orchRunControlClient';
import type { SubagentLiveState } from '../../../../shared/api/types/chatAndEventTypes';
import { TaskDetailView } from '../TaskDetailView';

vi.mock('../../../../shared/api/orchRunClient', () => ({
  orchRunClient: {
    cancelTask: vi.fn().mockResolvedValue(undefined),
  },
}));

vi.mock('../../../../shared/api/orchRunControlClient', () => ({
  orchRunControlClient: {
    getTaskTranscript: vi.fn().mockResolvedValue({
      run_id: 'run-1',
      task_id: 't1',
      messages: [],
      next_seq: 0,
      has_more: false,
    }),
    followupTask: vi.fn().mockResolvedValue({
      ok: true,
      run_id: 'run-1',
      parent_task_id: 't1',
      task_id: 'fu1',
      status: 'dispatched',
    }),
    pauseTask: vi.fn().mockResolvedValue({ ok: true, run_id: 'run-1', task_id: 't1', status: 'paused' }),
    resumeTask: vi.fn().mockResolvedValue({ ok: true, run_id: 'run-1', task_id: 't1', status: 'running' }),
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
    useRunControlStore.getState().resetAll();
  });

  it('切换到「对话」tab 渲染 Transcript 面板', async () => {
    const board = buildBoard();
    render(<TaskDetailView board={board} taskId="t1" onBack={vi.fn()} />);

    expect(screen.queryByTestId('task-transcript-panel')).not.toBeInTheDocument();

    fireEvent.click(screen.getByTestId('task-detail-tab-transcript'));

    expect(
      await screen.findByTestId('task-transcript-panel', {}, { timeout: 5000 }),
    ).toBeInTheDocument();
  });

  it('终态任务可在「对话」tab 继续追问并切换到新任务', async () => {
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
          output_preview: 'done',
        },
      },
    });
    const followupTaskMock = vi.mocked(orchRunControlClient.followupTask);
    const getTaskTranscriptMock = vi.mocked(orchRunControlClient.getTaskTranscript);
    followupTaskMock.mockClear();
    getTaskTranscriptMock.mockClear();

    render(<TaskDetailView board={board} taskId="t1" onBack={vi.fn()} />);
    fireEvent.click(screen.getByTestId('task-detail-tab-transcript'));

    const input = await screen.findByTestId(
      'task-transcript-followup-input',
      {},
      { timeout: 5000 },
    );
    fireEvent.change(input, { target: { value: '再补充第三节' } });
    fireEvent.click(screen.getByTestId('task-transcript-followup-submit'));

    await waitFor(() =>
      expect(followupTaskMock).toHaveBeenCalledWith('run-1', 't1', '再补充第三节'),
    );
    // 派发成功后详情页切换到新任务 fu1，transcript 轮询随之切换
    await waitFor(() =>
      expect(getTaskTranscriptMock).toHaveBeenCalledWith('run-1', 'fu1', 0, 200),
    );
  });

  it('M2.5: paused 任务显示已暂停并提供恢复按钮', async () => {
    const board = buildBoard({
      statuses: {
        t1: {
          state: 'task_status',
          run_id: 'run-1',
          task_id: 't1',
          status: 'paused',
          agent_id: 'researcher',
          goal: '搜集资料',
          error: null,
          output_preview: null,
        },
      },
    });
    const resumeTaskMock = vi.mocked(orchRunControlClient.resumeTask);
    resumeTaskMock.mockClear();

    render(<TaskDetailView board={board} taskId="t1" onBack={vi.fn()} />);

    expect(screen.getByTestId('task-detail-status')).toHaveTextContent('已暂停');
    const btn = screen.getByTestId('task-detail-pause');
    expect(btn).toHaveTextContent('恢复');
    fireEvent.click(btn);
    await waitFor(() => expect(resumeTaskMock).toHaveBeenCalledWith('run-1', 't1'));
  });

  it('M2.5: running 任务点击暂停调用 pauseTask', async () => {
    const board = buildBoard();
    const pauseTaskMock = vi.mocked(orchRunControlClient.pauseTask);
    pauseTaskMock.mockClear();

    render(<TaskDetailView board={board} taskId="t1" onBack={vi.fn()} />);

    const btn = screen.getByTestId('task-detail-pause');
    expect(btn).toHaveTextContent('暂停');
    fireEvent.click(btn);
    await waitFor(() => expect(pauseTaskMock).toHaveBeenCalledWith('run-1', 't1'));
  });

  it('run 已登记进 runControlStore 时渲染事件时间线与 steering 入口', () => {
    const board = buildBoard();
    const store = useRunControlStore.getState();
    store.setRunSnapshot({
      run_id: 'run-1',
      status: 'running',
      summary: {},
      last_event_seq: 1,
      updated_at: Date.now(),
      tasks: [],
    });
    store.applyEvent({
      event_id: 'evt-1',
      run_id: 'run-1',
      seq: 2,
      event_type: 'task.started',
      occurred_at: Date.now(),
      producer: 'chat-dispatcher',
      producer_generation: 1,
      entity: { task_id: 't1', agent_id: 'researcher' },
      payload: {},
      visibility: 'user',
      schema_version: '1',
    });

    render(<TaskDetailView board={board} taskId="t1" onBack={vi.fn()} />);

    expect(screen.getByText('事件时间线')).toBeInTheDocument();
    expect(screen.getByTestId('context-input')).toBeInTheDocument();
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
