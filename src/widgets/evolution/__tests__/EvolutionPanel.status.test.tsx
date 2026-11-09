/**
 * EvolutionPanel — 进化日志显示回归测试。
 *
 * 覆盖三个历史 bug:
 *   1. 状态值不匹配 —— 后端写 'success'，旧前端只认 'completed'，
 *      导致所有记录显示成灰色原始英文。
 *   2. 时间戳单位错误 —— 后端 created_at 是 Unix 秒，前端当毫秒用，
 *      日期显示成 1970 年。
 *   3. 错误静默吞掉 —— invoke 失败时页面空白，用户无感知。
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { EvolutionPanel } from '../EvolutionPanel';

const invokeMock = vi.fn();
vi.mock('../../../shared/api/desktopInvoke', () => ({
  invoke: (...args: unknown[]) => invokeMock(...args),
}));

// 2025-07-29T00:00:00Z —— Unix 秒
const CREATED_AT = 1753747200;

function makeLog(overrides: Record<string, unknown> = {}) {
  return {
    id: 'evo-1',
    evolution_type: 'daily_summary',
    description: '生成每日摘要',
    status: 'success',
    created_at: CREATED_AT,
    completed_at: null,
    ...overrides,
  };
}

describe('EvolutionPanel 状态显示', () => {
  beforeEach(() => {
    invokeMock.mockReset();
  });

  it('把后端的 success 状态渲染成中文「成功」', async () => {
    invokeMock.mockResolvedValue([makeLog({ status: 'success' })]);

    render(<EvolutionPanel />);

    expect(await screen.findByText('成功')).toBeTruthy();
    // 旧的错误状态值不应再出现
    expect(screen.queryByText('success')).toBeNull();
  });

  it('把 failed / skipped 状态渲染成对应中文标签', async () => {
    invokeMock.mockResolvedValue([
      makeLog({ id: 'evo-f', status: 'failed' }),
      makeLog({ id: 'evo-s', status: 'skipped' }),
    ]);

    render(<EvolutionPanel />);

    expect(await screen.findByText('失败')).toBeTruthy();
    expect(screen.getByText('跳过')).toBeTruthy();
  });

  it('未知状态回落到原始值，不吞掉信息', async () => {
    invokeMock.mockResolvedValue([makeLog({ status: 'running' })]);

    render(<EvolutionPanel />);

    expect(await screen.findByText('running')).toBeTruthy();
  });

  it('把秒级时间戳正确渲染成日期（不再是 1970 年）', async () => {
    invokeMock.mockResolvedValue([makeLog()]);

    render(<EvolutionPanel />);

    const rendered = await screen.findByText(/2025/);
    expect(rendered).toBeTruthy();
    expect(screen.queryByText(/1970/)).toBeNull();
  });

  it('invoke 失败时展示错误与重试按钮，不再静默空白', async () => {
    invokeMock.mockRejectedValueOnce(new Error('后端不可达'));

    render(<EvolutionPanel />);

    expect(await screen.findByText(/加载进化日志失败/)).toBeTruthy();
    expect(screen.getByText('重试')).toBeTruthy();
  });

  it('点击重试后重新拉取日志', async () => {
    invokeMock.mockRejectedValueOnce(new Error('后端不可达'));
    invokeMock.mockResolvedValueOnce([makeLog()]);

    render(<EvolutionPanel />);

    const retry = await screen.findByText('重试');
    fireEvent.click(retry);

    await waitFor(() => {
      expect(screen.getByText('成功')).toBeTruthy();
    });
    expect(invokeMock).toHaveBeenCalledTimes(2);
  });
});
