/**
 * BatchRegisterPanel 测试 (2026-09-19, P5)
 *
 * - 默认参数启动（count 3 / 代理 off）→ startRegistrationJob 被调用并出现监控台
 * - 非法数量（0）→ 本地校验报错，不发起请求
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  startRegistrationJob: vi.fn(),
  getRegistrationJob: vi.fn(),
  getRegistrationJobEvents: vi.fn(),
  stopRegistrationJob: vi.fn(),
  exportRegistrationJob: vi.fn(),
}));

vi.mock('../../../entities/arena', () => mocks);

import { BatchRegisterPanel } from '../BatchRegisterPanel';

afterEach(() => {
  vi.restoreAllMocks();
  for (const fn of Object.values(mocks)) fn.mockReset();
});

describe('BatchRegisterPanel', () => {
  it('默认参数启动注册任务并渲染监控台', async () => {
    mocks.startRegistrationJob.mockResolvedValue({ id: 'job-9', status: 'running' });
    mocks.getRegistrationJob.mockResolvedValue({
      id: 'job-9', kind: 'register', status: 'running', created_at: '',
      total: 3, done: 0, ok: 0, failed: 0, params: {}, result_count: 0, error: '', last_seq: 0,
    });
    mocks.getRegistrationJobEvents.mockResolvedValue([]);

    render(<BatchRegisterPanel />);
    fireEvent.click(screen.getByTestId('batch-start'));

    await waitFor(() =>
      expect(mocks.startRegistrationJob).toHaveBeenCalledWith({
        count: 3,
        concurrency: undefined,
        proxy_mode: 'off',
      }),
    );
    expect(await screen.findByTestId('job-console-job-9')).toBeInTheDocument();
  });

  it('数量 0 本地报错且不发起请求', async () => {
    render(<BatchRegisterPanel />);
    fireEvent.change(screen.getByTestId('batch-count'), { target: { value: '0' } });
    fireEvent.click(screen.getByTestId('batch-start'));
    expect(await screen.findByTestId('batch-error')).toHaveTextContent('1-20');
    expect(mocks.startRegistrationJob).not.toHaveBeenCalled();
  });
});
