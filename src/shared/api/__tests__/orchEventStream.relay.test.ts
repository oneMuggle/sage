/**
 * r101: orchEventStream Electron IPC relay 分支测试。
 *
 * stub window.electronAPI.listen 捕获 (eventName, handler) 注册，
 * 驱动事件/错误通道，覆盖 r96 未涉及的 relay 面：
 * - afterSeq=0 / >0 两种事件通道命名
 * - 信封产出、非法载荷忽略
 * - error 通道消息终结生成器
 * - abort 清理（unlisten 被调用、生成器收尾）
 *
 * 注意：生成器惰性执行 —— 必须先调 gen.next() 让主体跑到 await listen
 * 注册处，flush 后再从 handler 推事件。
 */
import { afterEach, describe, expect, it, vi } from 'vitest';

import { subscribeOrchEvents } from '../orchEventStream';
import type { RunEvent } from '../orchEvents';

function envelope(overrides: Partial<RunEvent> = {}): RunEvent {
  return {
    event_id: 'e-1',
    run_id: 'r1',
    seq: 1,
    event_type: 'task.started',
    occurred_at: 1,
    producer: 'lane-executor',
    producer_generation: 1,
    entity: { task_id: 't1' },
    payload: {},
    visibility: 'user',
    schema_version: '1',
    ...overrides,
  };
}

type Handler = (raw: unknown) => void;

function stubElectronListen() {
  const handlers = new Map<string, Handler>();
  const unlisten = vi.fn();
  const listen = vi.fn((eventName: string, handler: Handler) => {
    handlers.set(eventName, handler);
    // 生产 preload 返回 Promise<UnlistenFn>（error 通道结果会被 .catch 链上）
    return Promise.resolve(unlisten);
  });
  vi.stubGlobal('window', { electronAPI: { listen } });
  return { handlers, unlisten };
}

const flush = () => new Promise((r) => setTimeout(r, 0));

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('subscribeOrchEvents IPC relay 分支', () => {
  it('afterSeq=0 订阅 orch-events-{runId}，事件按序产出', async () => {
    const { handlers } = stubElectronListen();
    const gen = subscribeOrchEvents({ runId: 'r1' });
    const p1 = gen.next();
    const p2 = gen.next();
    await flush();

    const first = envelope({ seq: 1, event_id: 'e-1' });
    const second = envelope({ seq: 2, event_id: 'e-2', event_type: 'task.succeeded' });
    handlers.get('orch-events-r1')?.(first);
    handlers.get('orch-events-r1')?.(second);

    expect(await p1).toEqual({ value: first, done: false });
    expect(await p2).toEqual({ value: second, done: false });
    await gen.return(undefined);
  });

  it('afterSeq>0 订阅 orch-events-{runId}-seq-{n}', async () => {
    const { handlers } = stubElectronListen();
    const gen = subscribeOrchEvents({ runId: 'r1', afterSeq: 5 });
    const pending = gen.next();
    await flush();
    expect(handlers.has('orch-events-r1-seq-5')).toBe(true);
    // 生成器悬在 wakeup await 上，gen.return 不会返回；走 error 通道干净终结
    handlers.get('orch-events-r1-seq-5-error')?.(new Error('done'));
    await expect(pending).rejects.toThrow('done');
  });

  it('非法载荷被忽略（不产出不报错）', async () => {
    const { handlers } = stubElectronListen();
    const gen = subscribeOrchEvents({ runId: 'r1' });
    const pending = gen.next();
    await flush();

    handlers.get('orch-events-r1')?.({ garbage: true });
    handlers.get('orch-events-r1')?.(null);
    const valid = envelope({ seq: 9, event_id: 'e-9' });
    handlers.get('orch-events-r1')?.(valid);

    const r = await pending;
    expect(r.value).toEqual(valid);
    await gen.return(undefined);
  });

  it('error 通道消息终结生成器', async () => {
    const { handlers } = stubElectronListen();
    const gen = subscribeOrchEvents({ runId: 'r1' });
    const pending = gen.next();
    await flush();

    handlers.get('orch-events-r1-error')?.({ message: 'relay died' });
    await expect(pending).rejects.toThrow('relay died');
  });

  it('abort 后 unlisten 被调用且生成器收尾', async () => {
    const { handlers, unlisten } = stubElectronListen();
    const controller = new AbortController();
    const gen = subscribeOrchEvents({ runId: 'r1', signal: controller.signal });
    const p1 = gen.next();
    await flush();

    const first = envelope({ seq: 1 });
    handlers.get('orch-events-r1')?.(first);
    expect(await p1).toEqual({ value: first, done: false });

    controller.abort();
    await flush();
    expect(unlisten).toHaveBeenCalled();
    const r = await gen.next();
    expect(r.done).toBe(true);
  });
});
