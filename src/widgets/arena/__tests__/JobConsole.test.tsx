/**
 * JobConsole 测试 (2026-09-19, P5)
 *
 * - 事件增量轮询：after_seq 游标推进，日志行渲染
 * - 终态停止轮询并触发 onFinished（恰好一次）
 * - 停止按钮调用 stop API；注册任务终态显示导出
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  getRegistrationJob: vi.fn(),
  getRegistrationJobEvents: vi.fn(),
  getDrawJob: vi.fn(),
  getDrawJobEvents: vi.fn(),
  stopRegistrationJob: vi.fn(),
  stopDrawJob: vi.fn(),
  exportRegistrationJob: vi.fn(),
}));

vi.mock('../../../entities/arena', () => mocks);

import { JobConsole } from '../JobConsole';

const RUNNING = { id: 'job-1', kind: 'draw', status: 'running', created_at: '', total: 3, done: 1, ok: 1, failed: 0, params: {}, result_count: 1, error: '', last_seq: 2 };
const DONE = { ...RUNNING, status: 'done', ok: 3, done: 3, failed: 0 };

function event(seq: number, message: string) {
  return { seq, ts: '2026-09-19T12:00:00', level: 'info', kind: 'log', message, data: {} };
}

beforeEach(() => {
  URL.createObjectURL = vi.fn(() => 'blob:mock');
  URL.revokeObjectURL = vi.fn();
});

afterEach(() => {
  vi.restoreAllMocks();
  for (const fn of Object.values(mocks)) fn.mockReset();
});

describe('JobConsole', () => {
  it('增量轮询渲染事件行并在终态停止', async () => {
    const onFinished = vi.fn();
    let status = 'running';
    const afterSeqSeen: number[] = [];
    mocks.getDrawJob.mockImplementation(async () => (status === 'running' ? RUNNING : DONE));
    mocks.getDrawJobEvents.mockImplementation(async (_id: string, afterSeq: number) => {
      afterSeqSeen.push(afterSeq);
      if (afterSeq === 0) return [event(1, '账号 A 登录'), event(2, '第 1 轮完成')];
      if (afterSeq === 2) {
        status = 'done';
        return [event(3, '任务完成')];
      }
      return [];
    });

    render(<JobConsole kind="draw" jobId="job-1" pollIntervalMs={10} onFinished={onFinished} />);

    expect(await screen.findByTestId('job-event-1')).toHaveTextContent('账号 A 登录');
    await waitFor(() => expect(screen.getByTestId('job-event-3')).toBeInTheDocument());
    expect(afterSeqSeen[0]).toBe(0);
    expect(afterSeqSeen).toContain(2);

    await waitFor(() => expect(onFinished).toHaveBeenCalledTimes(1));
    expect(onFinished).toHaveBeenCalledWith(expect.objectContaining({ status: 'done' }));

    // 终态后不再轮询
    const calls = mocks.getDrawJobEvents.mock.calls.length;
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(mocks.getDrawJobEvents.mock.calls.length).toBe(calls);
    expect(screen.getByTestId('job-console-status').textContent).toContain('done');
  });

  it('停止按钮调用 stopDrawJob', async () => {
    mocks.getDrawJob.mockResolvedValue(RUNNING);
    mocks.getDrawJobEvents.mockResolvedValue([]);
    mocks.stopDrawJob.mockResolvedValue({ stopped: true });

    render(<JobConsole kind="draw" jobId="job-1" pollIntervalMs={10} />);
    fireEvent.click(await screen.findByTestId('job-console-stop'));
    await waitFor(() => expect(mocks.stopDrawJob).toHaveBeenCalledWith('job-1'));
  });

  it('注册任务终态提供导出（文本另存）', async () => {
    mocks.getRegistrationJob.mockResolvedValue({ ...DONE, kind: 'register' });
    mocks.getRegistrationJobEvents.mockResolvedValue([]);
    mocks.exportRegistrationJob.mockResolvedValue('[{"email":"a@b.c"}]');

    render(<JobConsole kind="register" jobId="job-1" pollIntervalMs={10} />);
    fireEvent.click(await screen.findByTestId('job-console-export'));
    await waitFor(() => expect(mocks.exportRegistrationJob).toHaveBeenCalledWith('job-1'));
    expect(URL.createObjectURL).toHaveBeenCalled();
  });
});
