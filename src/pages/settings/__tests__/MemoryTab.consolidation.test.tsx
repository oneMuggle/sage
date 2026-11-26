/**
 * R17-B / 2026-11-26: MemoryTab 记忆固化卡交互测试。
 *
 * 固化触发与结果由 evolutionRunStore 派生：点击后按钮进入运行中，
 * 完成（轮询到 succeeded）后回显统计；期间卸载再挂载（模拟切 tab）
 * 按钮仍保持运行中；触发失败弹错误 toast。
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { toast } from 'sonner';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';


import { useEvolutionRunStore } from '../../../entities/evolution/evolutionRunStore';
import { I18nProvider } from '../../../shared/lib/i18n';
import { MemoryTab } from '../MemoryTab';

const invokeMock = vi.fn();
vi.mock('../../../shared/api/desktopInvoke', () => ({
  invoke: (...args: unknown[]) => invokeMock(...args),
}));

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}));

function makeRun(overrides: Record<string, unknown> = {}) {
  return {
    run_id: 'run-consolidation',
    name: 'memory_consolidation',
    state: 'running',
    trigger: 'manual',
    phase: 'start',
    phase_label: '准备中',
    progress: {},
    started_at: Date.now() - 2_000,
    finished_at: null,
    duration_ms: null,
    result: null,
    error: null,
    ...overrides,
  };
}

function tasksPayload(run: Record<string, unknown>) {
  return {
    tasks: [
      {
        name: 'memory_consolidation',
        job_id: 'evolution/memory_consolidation',
        run,
      },
    ],
  };
}

function renderTab() {
  return render(
    <I18nProvider defaultLocale="zh">
      <MemoryTab />
    </I18nProvider>,
  );
}

describe('MemoryTab 记忆固化卡 (R17-B)', () => {
  beforeEach(() => {
    invokeMock.mockReset();
    useEvolutionRunStore.getState().reset();
    vi.mocked(toast.success).mockReset();
    vi.mocked(toast.error).mockReset();
  });

  afterEach(() => {
    useEvolutionRunStore.getState().reset();
  });

  it('触发固化后显示运行中，完成时回显统计并提示一次', async () => {
    let currentRun: Record<string, unknown> = makeRun();
    invokeMock.mockImplementation(async (cmd: string) => {
      if (cmd === 'scheduled_evolution_run') {
        return { ok: true, started: true, run: currentRun };
      }
      if (cmd === 'scheduled_evolution_tasks') {
        return tasksPayload(currentRun);
      }
      return null;
    });

    renderTab();
    fireEvent.click(screen.getByTestId('memory-consolidation-run'));

    await waitFor(() => {
      expect(screen.getByText(/固化中/)).toBeInTheDocument();
    });
    expect(screen.getByTestId('memory-consolidation-run')).toBeDisabled();

    currentRun = makeRun({
      state: 'succeeded',
      phase: 'done',
      phase_label: '完成',
      finished_at: Date.now(),
      duration_ms: 8_000,
      result: { promoted: 2, decayed: 5, total: 7 },
    });

    await waitFor(
      () =>
        expect(screen.getByTestId('memory-consolidation-result')).toHaveTextContent(
          /晋升 2 条 · 衰减 5 条/,
        ),
      { timeout: 5_000 },
    );
    expect(screen.getByTestId('memory-consolidation-run')).not.toBeDisabled();
    expect(toast.success).toHaveBeenCalledWith('记忆固化完成');
  });

  it('trigger 失败时弹错误 toast', async () => {
    invokeMock.mockImplementation(async (cmd: string) => {
      if (cmd === 'scheduled_evolution_run') {
        throw new Error('后端 503');
      }
      return null;
    });

    renderTab();
    fireEvent.click(screen.getByTestId('memory-consolidation-run'));

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith('固化失败: 后端 503'));
    expect(screen.queryByTestId('memory-consolidation-result')).not.toBeInTheDocument();
  });

  it('运行中卸载再挂载（切 tab）按钮仍保持禁用与运行中状态', async () => {
    invokeMock.mockImplementation(async (cmd: string) => {
      if (cmd === 'scheduled_evolution_run') {
        return { ok: true, started: true, run: makeRun() };
      }
      if (cmd === 'scheduled_evolution_tasks') {
        return tasksPayload(makeRun());
      }
      return null;
    });

    const first = renderTab();
    fireEvent.click(screen.getByTestId('memory-consolidation-run'));
    await waitFor(() => {
      expect(screen.getByTestId('memory-consolidation-run')).toBeDisabled();
    });
    first.unmount();

    renderTab();
    const button = screen.getByTestId('memory-consolidation-run');
    expect(button).toBeDisabled();
    expect(button).toHaveTextContent(/固化中/);
  });
});
