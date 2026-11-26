/**
 * evolutionRunStore 测试（2026-11-26 进化任务进度可见）。
 *
 * 核心回归：轮询在 store 层持续（组件卸载不丢）、running → 终态只提示一次、
 * 触发后立即拿到 running 快照、连续失败停止轮询。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const { invokeMock, toastMock } = vi.hoisted(() => ({
  invokeMock: vi.fn(),
  toastMock: { success: vi.fn(), error: vi.fn() },
}));
vi.mock('../../../shared/api/desktopInvoke', () => ({ invoke: invokeMock }));
vi.mock('sonner', () => ({ toast: toastMock }));

import { EVOLUTION_RUN_POLL_MS, useEvolutionRunStore } from '../evolutionRunStore';

function makeRun(overrides: Record<string, unknown> = {}) {
  const now = Date.now();
  return {
    run_id: 'run-1',
    name: 'memory_reflection',
    state: 'running',
    trigger: 'manual',
    phase: 'llm',
    phase_label: 'LLM 合并',
    progress: { scanned: 12, llm_done: 1, llm_total: 3 },
    started_at: now - 5_000,
    finished_at: null,
    duration_ms: null,
    result: null,
    error: null,
    ...overrides,
  };
}

function tasksPayload(run: Record<string, unknown>) {
  return {
    tasks: [{ name: 'memory_reflection', job_id: 'evolution/memory_reflection', run }],
  };
}

describe('useEvolutionRunStore', () => {
  beforeEach(() => {
    invokeMock.mockReset();
    toastMock.success.mockReset();
    toastMock.error.mockReset();
    useEvolutionRunStore.getState().reset();
  });

  afterEach(() => {
    vi.useRealTimers();
    useEvolutionRunStore.getState().reset();
  });

  it('refresh 把 tasks 的 run 快照映射进 runs', async () => {
    invokeMock.mockResolvedValue(tasksPayload(makeRun()));

    await useEvolutionRunStore.getState().refresh();

    const runs = useEvolutionRunStore.getState().runs;
    expect(runs.memory_reflection.state).toBe('running');
    expect(runs.memory_reflection.phase_label).toBe('LLM 合并');
  });

  it('running 时在 store 层轮询，结束后自动停止', async () => {
    vi.useFakeTimers();
    let run = makeRun();
    invokeMock.mockImplementation(async (cmd: string) =>
      cmd === 'scheduled_evolution_tasks' ? tasksPayload(run) : null,
    );

    await useEvolutionRunStore.getState().refresh();
    expect(invokeMock).toHaveBeenCalledTimes(1);

    run = makeRun({
      state: 'succeeded',
      phase: 'done',
      phase_label: '完成',
      finished_at: Date.now(),
      duration_ms: 4_200,
      result: { deduped: 2 },
    });
    await vi.advanceTimersByTimeAsync(EVOLUTION_RUN_POLL_MS);
    expect(invokeMock).toHaveBeenCalledTimes(2);

    await vi.advanceTimersByTimeAsync(EVOLUTION_RUN_POLL_MS * 3);
    expect(invokeMock).toHaveBeenCalledTimes(2);
  });

  it('只对观察到的 running → 终态转换提示一次完成', async () => {
    vi.useFakeTimers();
    let run = makeRun();
    invokeMock.mockImplementation(async () => tasksPayload(run));

    await useEvolutionRunStore.getState().refresh();
    expect(toastMock.success).not.toHaveBeenCalled();

    run = makeRun({ state: 'succeeded', finished_at: Date.now(), result: { deduped: 2 } });
    await vi.advanceTimersByTimeAsync(EVOLUTION_RUN_POLL_MS);

    expect(toastMock.success).toHaveBeenCalledTimes(1);
    expect(toastMock.success).toHaveBeenCalledWith('记忆整理完成');
  });

  it('失败终态提示错误信息', async () => {
    vi.useFakeTimers();
    let run = makeRun();
    invokeMock.mockImplementation(async () => tasksPayload(run));

    await useEvolutionRunStore.getState().refresh();
    run = makeRun({ state: 'failed', error: 'boom', finished_at: Date.now() });
    await vi.advanceTimersByTimeAsync(EVOLUTION_RUN_POLL_MS);

    expect(toastMock.error).toHaveBeenCalledWith('记忆整理失败：boom');
  });

  it('首次挂载看到历史终态不弹完成提示', async () => {
    invokeMock.mockResolvedValue(
      tasksPayload(makeRun({ state: 'succeeded', finished_at: Date.now() })),
    );

    await useEvolutionRunStore.getState().refresh();

    expect(toastMock.success).not.toHaveBeenCalled();
  });

  it('trigger 调用 scheduled_evolution_run 并立即刷新出 running 快照', async () => {
    invokeMock.mockImplementation(async (cmd: string) => {
      if (cmd === 'scheduled_evolution_run') {
        return { ok: true, started: true, run: makeRun() };
      }
      if (cmd === 'scheduled_evolution_tasks') {
        return tasksPayload(makeRun());
      }
      return null;
    });

    const snapshot = await useEvolutionRunStore.getState().trigger('memory_reflection');

    expect(invokeMock).toHaveBeenCalledWith('scheduled_evolution_run', {
      name: 'memory_reflection',
    });
    expect(snapshot?.state).toBe('running');
    expect(useEvolutionRunStore.getState().runs.memory_reflection.state).toBe('running');
  });

  it('trigger 启动失败时抛错（ok=false）', async () => {
    invokeMock.mockResolvedValue({ ok: false, detail: 'task not registered' });

    await expect(useEvolutionRunStore.getState().trigger('memory_reflection')).rejects.toThrow(
      'task not registered',
    );
  });

  it('连续 3 次轮询失败后停止轮询', async () => {
    vi.useFakeTimers();
    invokeMock.mockImplementation(async () => tasksPayload(makeRun()));

    await useEvolutionRunStore.getState().refresh();
    expect(invokeMock).toHaveBeenCalledTimes(1);

    invokeMock.mockRejectedValue(new Error('backend down'));
    await vi.advanceTimersByTimeAsync(EVOLUTION_RUN_POLL_MS); // 失败 1
    await vi.advanceTimersByTimeAsync(EVOLUTION_RUN_POLL_MS); // 失败 2
    await vi.advanceTimersByTimeAsync(EVOLUTION_RUN_POLL_MS); // 失败 3 → 停止
    const callsAfterStop = invokeMock.mock.calls.length;

    await vi.advanceTimersByTimeAsync(EVOLUTION_RUN_POLL_MS * 3);
    expect(invokeMock.mock.calls.length).toBe(callsAfterStop);
    expect(useEvolutionRunStore.getState().error).toBe('backend down');
  });
});
