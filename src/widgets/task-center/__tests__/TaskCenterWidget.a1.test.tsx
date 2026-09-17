/**
 * A1 (parity-s4): TaskCenterWidget 状态徽章 / 取消 / 最近完成。
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { useLaneBoardStore } from '../../../entities/orchestration/laneBoardStore';
import {
  useChatStreamStore,
  type SessionStreamSlots,
} from '../../../features/send-message/chatStreamStore';
import { cancelSessionStream } from '../../../features/send-message/useChat';
import { useTaskCenterStore } from '../../../features/task-center/taskCenterStore';
import type { Lane } from '../../../shared/api/types';
import { I18nProvider } from '../../../shared/lib/i18n';
import { useStore } from '../../../shared/lib/store';
import { TaskCenterWidget } from '../TaskCenterWidget';

vi.mock('../../../features/send-message/useChat', () => ({
  cancelSessionStream: vi.fn(async () => true),
}));

const mockedCancel = vi.mocked(cancelSessionStream);

const slot = (messageId: string, streaming: boolean): SessionStreamSlots => ({
  streaming: streaming
    ? {
        messageId,
        content: '',
        reasoning: '',
        state: null,
        currentAgentId: null,
        iteration: 0,
      }
    : null,
  streamingToolCalls: [],
  taskBoard: null,
  todos: [],
  completedSteps: [],
});

function seedLane(overrides: Partial<Lane> = {}): Lane {
  return {
    lane_id: 'lane-1',
    task_id: 't1',
    agent_id: 'agent-a',
    status: 'running',
    created_at: Date.now(),
    started_at: Date.now(),
    completed_at: null,
    worktree: null,
    heartbeat: null,
    error: null,
    permission_preset: 'standard',
    metadata: {},
    ...overrides,
  };
}

function renderWidget() {
  return render(
    <MemoryRouter>
      <I18nProvider defaultLocale="zh">
        <TaskCenterWidget />
      </I18nProvider>
    </MemoryRouter>,
  );
}

describe('TaskCenterWidget 状态机 (A1)', () => {
  beforeEach(() => {
    useTaskCenterStore.setState({ tasks: {} });
    useChatStreamStore.setState({ sessions: {} });
    useLaneBoardStore.setState({ lanes: [] });
    useStore.setState({ currentSessionId: null, sessions: [] } as never);
    mockedCancel.mockClear();
    mockedCancel.mockResolvedValue(true);
  });

  it('失败条目渲染错误行，清除已完成可移除', () => {
    useTaskCenterStore.getState().registerTask('office:gen', 'office', '生成 PPT');
    useTaskCenterStore.getState().completeTask('office:gen', 'failed', '模型超时');

    renderWidget();
    expect(screen.getByTestId('task-center-toggle')).toHaveTextContent('1');

    fireEvent.click(screen.getByTestId('task-center-toggle'));
    expect(screen.getByText('生成 PPT')).toBeInTheDocument();
    expect(screen.getByText('模型超时')).toBeInTheDocument();

    fireEvent.click(screen.getByTestId('task-center-clear'));
    expect(screen.queryByTestId('task-center')).not.toBeInTheDocument();
  });

  it('运行中的 registry 条目无取消按钮、无清除按钮', () => {
    useTaskCenterStore.getState().registerTask('office:gen', 'office', '生成 PPT');
    renderWidget();
    fireEvent.click(screen.getByTestId('task-center-toggle'));

    expect(screen.getByText('生成 PPT')).toBeInTheDocument();
    expect(screen.queryByTestId('task-center-cancel-office:gen')).not.toBeInTheDocument();
    expect(screen.queryByTestId('task-center-clear')).not.toBeInTheDocument();
  });

  it('后台 chat 流条目可取消', async () => {
    useStore.setState({
      currentSessionId: 'sess-cur',
      sessions: [{ id: 'sess-bg', title: '后台会话' }] as never,
    } as never);
    useChatStreamStore.setState({ sessions: { 'sess-bg': slot('m-bg', true) } });

    renderWidget();
    fireEvent.click(screen.getByTestId('task-center-toggle'));
    expect(screen.getByText('后台会话')).toBeInTheDocument();

    fireEvent.click(screen.getByTestId('task-center-cancel-chat:sess-bg'));
    await waitFor(() => expect(mockedCancel).toHaveBeenCalledWith('sess-bg'));
  });

  it('运行中的 lane 条目渲染并可取消', async () => {
    const cancelSpy = vi.fn(async () => {});
    useLaneBoardStore.setState({ lanes: [seedLane()], cancel: cancelSpy });

    renderWidget();
    fireEvent.click(screen.getByTestId('task-center-toggle'));
    expect(screen.getByText(/t1/)).toBeInTheDocument();

    fireEvent.click(screen.getByTestId('task-center-cancel-lane:lane-1'));
    await waitFor(() => expect(cancelSpy).toHaveBeenCalledWith('lane-1'));
  });

  it('失败的 lane 展示错误且不可取消', () => {
    useLaneBoardStore.setState({
      lanes: [seedLane({ status: 'failed', error: 'runner 崩溃' })],
    });

    renderWidget();
    fireEvent.click(screen.getByTestId('task-center-toggle'));
    expect(screen.getByText('runner 崩溃')).toBeInTheDocument();
    expect(screen.queryByTestId('task-center-cancel-lane:lane-1')).not.toBeInTheDocument();
  });
});
