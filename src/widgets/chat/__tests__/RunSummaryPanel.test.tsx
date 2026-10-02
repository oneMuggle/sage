// @vitest-environment jsdom
import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { useChangesListStore } from '../../../features/changes/changesListStore';
import type { TaskBoardState } from '../../../features/send-message/chatStreamStore';
import { useChatStreamStore } from '../../../features/send-message/chatStreamStore';
import { RunSummaryPanel } from '../RunSummaryPanel';

const SESSION = 'sess-1';
const MSG = 'msg-1';

function seedBoard(overrides: Partial<TaskBoardState> = {}, streaming = false) {
  const board: TaskBoardState = {
    runId: 'run-1',
    plan: [],
    statuses: {},
    dispatchedAt: Date.now(),
    ...overrides,
  };
  // 走 store 自己的 action，而不是 setState 手搓半个状态。
  // 此前这里直接构造 `{ state, currentAgentId, iteration }` 当 StreamingState ——
  // 那缺 messageId/content/reasoning，是个运行时碰巧不炸的假状态：面板只读
  // `.state` 所以测试通过，但任何读 content 的代码加进来就会静默拿到 undefined。
  const store = useChatStreamStore.getState();
  store.startStream(SESSION, MSG);
  store.setStreamingMeta(SESSION, MSG, {
    // 面板判「还在跑」的口径是 state !== 'done'，所以给一个真实的中途态
    // （acting = 子代理正在执行）即可，'running' 根本不是 AgentState 的取值。
    state: streaming ? 'acting' : 'done',
    currentAgentId: null,
    iteration: 1,
  });
  // startStream 会把 taskBoard 置空，所以必须在它之后写板子
  store.setTaskBoard(SESSION, board);
}

beforeEach(() => {
  useChatStreamStore.setState({ sessions: {} } as never);
  useChangesListStore.setState({ bySession: {}, errors: {}, loadingBy: {} } as never);
  // 默认不让它真的去拉 workspace 变更（各用例按需覆盖）
  useChangesListStore.setState({ fetch: vi.fn().mockResolvedValue(undefined) } as never);
});

describe('RunSummaryPanel (P2-6)', () => {
  it('运行中不渲染 —— 与 SubagentLivePanel 互斥', () => {
    seedBoard(
      { progress: { total: 2, done: 1, running: 1, queued: 0, failed: 0, cancelled: 0 } },
      true,
    );
    const { container } = render(<RunSummaryPanel sessionId={SESSION} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('普通对话（无 taskBoard）不渲染', () => {
    const { container } = render(<RunSummaryPanel sessionId={SESSION} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('终态时给出任务计数', () => {
    seedBoard({ progress: { total: 5, done: 3, running: 0, queued: 0, failed: 2, cancelled: 0 } });
    render(<RunSummaryPanel sessionId={SESSION} />);
    expect(screen.getByTestId('run-summary-progress')).toHaveTextContent('共 5 个子任务');
    expect(screen.getByTestId('run-summary-progress')).toHaveTextContent('失败 2');
  });

  it('逐条列出失败任务的目标与错误原因', () => {
    seedBoard({
      statuses: {
        t1: {
          state: 'task_status',
          run_id: 'run-1',
          task_id: 't1',
          status: 'done',
          agent_id: 'coder',
          goal: '实现登录',
          error: null,
          output_preview: null,
        },
        t2: {
          state: 'task_status',
          run_id: 'run-1',
          task_id: 't2',
          status: 'failed',
          agent_id: 'tester',
          goal: '补充测试',
          error: '超时未返回',
          output_preview: null,
          retry_count: 2,
        },
      },
    });
    render(<RunSummaryPanel sessionId={SESSION} />);
    const failures = screen.getByTestId('run-summary-failures');
    expect(failures).toHaveTextContent('补充测试');
    expect(screen.getByTestId('run-summary-error')).toHaveTextContent('超时未返回');
    expect(failures).toHaveTextContent('已重试 2 次');
    // 成功的任务不该出现在「未完成」里
    expect(failures).not.toHaveTextContent('实现登录');
  });

  it('取消的任务也计入未完成', () => {
    seedBoard({
      statuses: {
        t3: {
          state: 'task_status',
          run_id: 'run-1',
          task_id: 't3',
          status: 'cancelled',
          agent_id: 'coder',
          goal: '重构模块',
          error: null,
          output_preview: null,
        },
      },
    });
    render(<RunSummaryPanel sessionId={SESSION} />);
    expect(screen.getByTestId('run-summary-failures')).toHaveTextContent('重构模块');
  });

  it('有失败任务时提供重跑入口', () => {
    const onRerunFailed = vi.fn();
    seedBoard({
      statuses: {
        t4: {
          state: 'task_status',
          run_id: 'run-1',
          task_id: 't4',
          status: 'failed',
          agent_id: 'coder',
          goal: 'x',
          error: 'boom',
          output_preview: null,
        },
      },
    });
    render(<RunSummaryPanel sessionId={SESSION} onRerunFailed={onRerunFailed} />);
    expect(screen.getByTestId('run-summary-rerun')).toBeInTheDocument();
  });

  it('文件变更如实标注为「会话工作区」而非本次 run 的改动', () => {
    // 关键诚实性约束：后端 workspace changes 没有 run 归属。
    // 文案夸大归属会让用户以为能按 run 找回滚范围。
    seedBoard({ progress: { total: 1, done: 1, running: 0, queued: 0, failed: 0, cancelled: 0 } });
    useChangesListStore.setState({
      bySession: {
        [SESSION]: {
          branch: 'main',
          upstream: 'origin/main',
          ahead: 0,
          behind: 0,
          clean: false,
          changes: [
            {
              indexStatus: 'M',
              worktreeStatus: 'M',
              path: 'src/a.ts',
              insertions: 12,
              deletions: 3,
            },
          ],
        },
      },
    } as never);
    render(<RunSummaryPanel sessionId={SESSION} />);
    const files = screen.getByTestId('run-summary-files');
    expect(files).toHaveTextContent('本次会话工作区变更 1 个文件');
    expect(files).toHaveTextContent('src/a.ts');
    expect(files).toHaveTextContent('+12');
    expect(files).toHaveTextContent('−3');
  });

  it('未绑定 git 仓库时如实显示不可用原因，不静默隐藏', () => {
    seedBoard({ progress: { total: 1, done: 1, running: 0, queued: 0, failed: 0, cancelled: 0 } });
    useChangesListStore.setState({
      errors: { [SESSION]: '当前会话尚未绑定工作区，无法查看变更' },
    } as never);
    render(<RunSummaryPanel sessionId={SESSION} />);
    const err = screen.getByTestId('run-summary-changes-error');
    expect(err).toHaveTextContent('无法读取文件变更');
    expect(err).toHaveTextContent('尚未绑定工作区');
  });

  it('三个维度全空时不渲染空壳', () => {
    // taskBoard 存在但既无 progress、也无失败任务、也无文件变更 → 没有可汇报内容
    seedBoard();
    const { container } = render(<RunSummaryPanel sessionId={SESSION} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('终态时才拉取工作区变更，运行中不拉', async () => {
    const fetch = vi.fn().mockResolvedValue(undefined);
    useChangesListStore.setState({ fetch } as never);
    seedBoard(
      { progress: { total: 1, done: 0, running: 1, queued: 0, failed: 0, cancelled: 0 } },
      true,
    );
    render(<RunSummaryPanel sessionId={SESSION} />);
    expect(fetch).not.toHaveBeenCalled();

    useChatStreamStore.getState().setStreamingMeta(SESSION, MSG, {
      state: 'done',
      currentAgentId: null,
      iteration: 2,
    });
    await waitFor(() => expect(fetch).toHaveBeenCalledWith(SESSION));
  });
});
