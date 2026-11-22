// @vitest-environment jsdom
/**
 * TaskTranscriptPanel 测试（M1）—— 消息级过程记录渲染。
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { TaskTranscriptResponse } from '../../../../shared/api/orchEvents';
import { orchRunControlClient } from '../../../../shared/api/orchRunControlClient';
import { TaskTranscriptPanel } from '../TaskTranscriptPanel';

vi.mock('../../../../shared/api/orchRunControlClient', () => ({
  orchRunControlClient: {
    getTaskTranscript: vi.fn(),
  },
}));

const getTaskTranscriptMock = vi.mocked(orchRunControlClient.getTaskTranscript);

function fixture(): TaskTranscriptResponse {
  return {
    run_id: 'run-1',
    task_id: 't1',
    next_seq: 5,
    has_more: false,
    messages: [
      {
        seq: 1,
        role: 'user',
        message_type: 'goal',
        content: '调研论文',
        reasoning: null,
        tool_name: null,
        tool_call_id: null,
        tool_args: null,
        tool_result: null,
        is_error: false,
        duration_ms: null,
        created_at: 1_700_000_000_000,
      },
      {
        seq: 2,
        role: 'assistant',
        message_type: 'reasoning',
        content: null,
        reasoning: '先确定检索策略',
        tool_name: null,
        tool_call_id: null,
        tool_args: null,
        tool_result: null,
        is_error: false,
        duration_ms: null,
        created_at: 1_700_000_000_001,
      },
      {
        seq: 3,
        role: 'assistant',
        message_type: 'tool_call',
        content: null,
        reasoning: null,
        tool_name: 'web_search',
        tool_call_id: 'call-1',
        tool_args: { q: 'sage' },
        tool_result: null,
        is_error: false,
        duration_ms: null,
        created_at: 1_700_000_000_002,
      },
      {
        seq: 4,
        role: 'tool',
        message_type: 'tool_result',
        content: null,
        reasoning: null,
        tool_name: null,
        tool_call_id: 'call-1',
        tool_args: null,
        tool_result: '检索结果',
        is_error: false,
        duration_ms: 42,
        created_at: 1_700_000_000_003,
      },
      {
        seq: 5,
        role: 'assistant',
        message_type: 'assistant',
        content: '结论：Sage 支持编排',
        reasoning: null,
        tool_name: null,
        tool_call_id: null,
        tool_args: null,
        tool_result: null,
        is_error: false,
        duration_ms: null,
        created_at: 1_700_000_000_004,
      },
    ],
  };
}

describe('TaskTranscriptPanel', () => {
  beforeEach(() => {
    getTaskTranscriptMock.mockReset();
  });

  it('渲染 goal / 思考 / 工具调用与结果 / 正文', async () => {
    getTaskTranscriptMock.mockResolvedValue(fixture());

    render(<TaskTranscriptPanel runId="run-1" taskId="t1" live={false} />);

    await waitFor(() =>
      expect(screen.getByTestId('task-transcript-goal')).toHaveTextContent('调研论文'),
    );
    expect(screen.getByTestId('task-transcript-reasoning')).toHaveTextContent('思考');
    expect(screen.getByTestId('task-transcript-tool-call')).toHaveTextContent('web_search');
    expect(screen.getByTestId('task-transcript-tool-result')).toHaveTextContent('检索结果');
    expect(screen.getByTestId('task-transcript-assistant')).toHaveTextContent(
      '结论：Sage 支持编排',
    );
    expect(getTaskTranscriptMock).toHaveBeenCalledWith('run-1', 't1', 0, 200);
  });

  it('没有记录时显示空态', async () => {
    getTaskTranscriptMock.mockResolvedValue({
      run_id: 'run-1',
      task_id: 't1',
      messages: [],
      next_seq: 0,
      has_more: false,
    });

    render(<TaskTranscriptPanel runId="run-1" taskId="t1" live={false} />);

    await waitFor(() =>
      expect(screen.getByTestId('task-transcript-empty')).toHaveTextContent('暂无过程记录'),
    );
  });

  it('父任务可续聊时显示输入框并回调 onFollowup', async () => {
    getTaskTranscriptMock.mockResolvedValue(fixture());
    const onFollowup = vi.fn();

    render(
      <TaskTranscriptPanel
        runId="run-1"
        taskId="t1"
        live={false}
        canFollowup
        onFollowup={onFollowup}
      />,
    );

    const input = await screen.findByTestId('task-transcript-followup-input');
    fireEvent.change(input, { target: { value: '再补充第三节' } });
    fireEvent.click(screen.getByTestId('task-transcript-followup-submit'));

    expect(onFollowup).toHaveBeenCalledWith('再补充第三节');
    // 提交后清空草稿
    expect((input as HTMLInputElement).value).toBe('');
  });

  it('不可续聊时不显示输入框', async () => {
    getTaskTranscriptMock.mockResolvedValue(fixture());

    render(<TaskTranscriptPanel runId="run-1" taskId="t1" live={false} />);

    await waitFor(() =>
      expect(screen.getByTestId('task-transcript-goal')).toBeInTheDocument(),
    );
    expect(screen.queryByTestId('task-transcript-followup')).toBeNull();
  });

  it('拉取失败时展示错误而不是崩溃', async () => {
    getTaskTranscriptMock.mockRejectedValue(new Error('ipc down'));

    render(<TaskTranscriptPanel runId="run-1" taskId="t1" live={false} />);

    await waitFor(() =>
      expect(screen.getByTestId('task-transcript-fetch-error')).toHaveTextContent('ipc down'),
    );
  });
});
