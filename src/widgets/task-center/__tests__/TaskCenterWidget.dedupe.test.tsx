/**
 * P5 去重收敛: 任务中心排除当前会话的流（其状态由 Chat 页内指示表达），
 * 只列后台会话；后台会话条目补记首见时间以显示已耗时。
 */
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, beforeEach } from 'vitest';

import { useChatStreamStore, type SessionStreamSlots } from '../../../features/send-message/chatStreamStore';
import { useTaskCenterStore } from '../../../features/task-center/taskCenterStore';
import { I18nProvider } from '../../../shared/lib/i18n';
import { useStore } from '../../../shared/lib/store';
import { TaskCenterWidget } from '../TaskCenterWidget';

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
});

function seed(opts: {
  currentSessionId: string;
  streamingSessions: { id: string; streaming: boolean }[];
}) {
  useStore.setState({
    currentSessionId: opts.currentSessionId,
    sessions: opts.streamingSessions.map((s, i) => ({
      id: s.id,
      title: `会话 ${s.id}`,
      created_at: i,
      updated_at: i,
      last_message_at: i,
    })),
  } as never);
  useChatStreamStore.setState({
    sessions: Object.fromEntries(
      opts.streamingSessions.map((s) => [s.id, slot(`m-${s.id}`, s.streaming)]),
    ),
  } as never);
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

describe('TaskCenterWidget 去重收敛 (P5)', () => {
  beforeEach(() => {
    useTaskCenterStore.setState({ tasks: {} });
    useChatStreamStore.setState({ sessions: {} });
  });

  it('当前会话的流不计入任务中心，后台会话计入', () => {
    seed({
      currentSessionId: 'sess-cur',
      streamingSessions: [
        { id: 'sess-cur', streaming: true },
        { id: 'sess-bg', streaming: true },
      ],
    });
    renderWidget();
    expect(screen.getByTestId('task-center-toggle')).toHaveTextContent('1');

    fireEvent.click(screen.getByTestId('task-center-toggle'));
    expect(screen.getByText('会话 sess-bg')).toBeInTheDocument();
    expect(screen.queryByText('会话 sess-cur')).not.toBeInTheDocument();
  });

  it('后台会话流结束后从任务中心消失（回到 0 项不渲染胶囊）', () => {
    seed({
      currentSessionId: 'sess-cur',
      streamingSessions: [{ id: 'sess-bg', streaming: true }],
    });
    const { unmount } = renderWidget();
    expect(screen.getByTestId('task-center-toggle')).toHaveTextContent('1');
    unmount();

    useChatStreamStore.setState({
      sessions: { 'sess-bg': slot('m-bg', false) },
    });
    renderWidget();
    expect(screen.queryByTestId('task-center')).not.toBeInTheDocument();
  });

  it('注册任务与后台流并存时计数合并', () => {
    useTaskCenterStore.getState().registerTask('office:generate', 'office', '生成 PPT');
    seed({
      currentSessionId: 'sess-cur',
      streamingSessions: [{ id: 'sess-bg', streaming: true }],
    });
    renderWidget();
    expect(screen.getByTestId('task-center-toggle')).toHaveTextContent('2');
  });
});
