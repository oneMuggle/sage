/**
 * EvolutionPanel — 进化日志与运行态显示回归测试。
 *
 * 覆盖历史 bug:
 *   1. 状态值不匹配 —— 后端写 'success'，旧前端只认 'completed'
 *   2. 时间戳单位错误 —— 后端 created_at 是 Unix 秒
 *   3. 错误静默吞掉 —— invoke 失败时页面空白
 *
 * 2026-11-26 增补：手动任务运行态由 evolutionRunStore 持有 ——
 * 触发后显示阶段进度；重新挂载（模拟切 tab / 去聊天页）状态不丢；
 * 完成后的统计摘要立即出现（游标不展示）。
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { useEvolutionRunStore } from '../../../entities/evolution/evolutionRunStore';
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

function makeRunSnapshot(overrides: Record<string, unknown> = {}) {
  return {
    run_id: 'run-1',
    name: 'memory_reflection',
    state: 'running',
    trigger: 'manual',
    phase: 'llm',
    phase_label: 'LLM 合并',
    progress: {
      scanned: 120,
      recent_scanned: 100,
      backlog_scanned: 20,
      deduped: 3,
      llm_done: 3,
      llm_total: 8,
    },
    started_at: Date.now() - 5_000,
    finished_at: null,
    duration_ms: null,
    result: null,
    error: null,
    ...overrides,
  };
}

function tasksPayload(run: Record<string, unknown> | null) {
  return {
    tasks: [
      {
        name: 'memory_reflection',
        job_id: 'evolution/memory_reflection',
        run,
      },
    ],
  };
}

describe('EvolutionPanel 状态显示', () => {
  beforeEach(() => {
    invokeMock.mockReset();
    useEvolutionRunStore.getState().reset();
  });

  afterEach(() => {
    useEvolutionRunStore.getState().reset();
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

  it('把 skipped_no_llm 渲染成「跳过（无 LLM）」而非原始字符串', async () => {
    invokeMock.mockResolvedValue([makeLog({ id: 'evo-nl', status: 'skipped_no_llm' })]);

    render(<EvolutionPanel />);

    expect(await screen.findByText('跳过（无 LLM）')).toBeTruthy();
    expect(screen.queryByText('skipped_no_llm')).toBeNull();
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
    invokeMock.mockResolvedValue([makeLog()]);

    render(<EvolutionPanel />);

    const retry = await screen.findByText('重试');
    fireEvent.click(retry);

    await waitFor(() => {
      expect(screen.getByText('成功')).toBeTruthy();
    });
    const logCalls = invokeMock.mock.calls.filter(([cmd]) => cmd === 'get_evolution_logs');
    expect(logCalls).toHaveLength(2);
  });

  it('触发任务后显示当前阶段，完成后展示统计摘要（游标不展示）', async () => {
    let currentRun: Record<string, unknown> = makeRunSnapshot();
    invokeMock.mockImplementation(async (cmd: string) => {
      if (cmd === 'get_evolution_logs') return [makeLog()];
      if (cmd === 'scheduled_evolution_tasks') {
        return tasksPayload(currentRun);
      }
      if (cmd === 'scheduled_evolution_run') {
        return { ok: true, started: true, run: currentRun };
      }
      return null;
    });

    render(<EvolutionPanel />);
    const button = await screen.findByTestId('evolution-run-memory_reflection');
    fireEvent.click(button);

    await waitFor(() => {
      expect(screen.getByText(/整理中 · LLM 合并/)).toBeTruthy();
    });
    expect(button).toBeDisabled();
    expect(screen.getByTestId('evolution-run-progress')).toHaveTextContent('LLM 合并 3/8');

    currentRun = makeRunSnapshot({
      state: 'succeeded',
      phase: 'done',
      phase_label: '完成',
      finished_at: Date.now(),
      duration_ms: 42_000,
      result: {
        scanned: 120,
        deduped: 3,
        merged: 1,
        invalidated: 2,
        reflection_backlog_cursor_ms: 123,
      },
    });

    await waitFor(
      () => {
        expect(screen.getByTestId('evolution-run-result')).toHaveTextContent('deduped: 3');
      },
      { timeout: 5_000 },
    );
    const result = screen.getByTestId('evolution-run-result');
    expect(result).not.toHaveTextContent('reflection_backlog_cursor_ms');
    expect(button).not.toBeDisabled();
  });

  it('重新挂载后从 store 恢复运行中状态（切 tab / 换页面不丢）', async () => {
    invokeMock.mockImplementation(async (cmd: string) => {
      if (cmd === 'get_evolution_logs') return [makeLog()];
      if (cmd === 'scheduled_evolution_tasks') return tasksPayload(makeRunSnapshot());
      return null;
    });

    const first = render(<EvolutionPanel />);
    const firstButton = await screen.findByTestId('evolution-run-memory_reflection');
    await waitFor(() => expect(firstButton).toBeDisabled());
    first.unmount();

    render(<EvolutionPanel />);
    const secondButton = await screen.findByTestId('evolution-run-memory_reflection');
    expect(secondButton).toBeDisabled();
    expect(screen.getByText(/整理中/)).toBeTruthy();
    expect(screen.getByTestId('evolution-run-progress')).toBeTruthy();
  });
});
