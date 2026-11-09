/**
 * 后端就绪前 IPC 请求队列 (electron/backendReadyQueue.ts) 单测。
 *
 * 背景：PR #2976 让主窗口先于后端 ready 展示，窗口期内渲染层的首屏
 * IPC（loadSessions / workspace bind 等）全部被 readiness gate 拒绝，
 * 且组件无重试路径 → 会话列表为空 / 工作台常驻错误横幅。
 *
 * 修复：窗口期请求入队，后端 ready 后 flush；仅在终止状态下 rejectAll。
 * 本测试锁定队列语义（FIFO、幂等 drain、溢出拒绝、可复用）。
 */
import { describe, expect, it, vi } from 'vitest';
import { BackendNotReadyError } from '../invoke';
import { createBackendReadyQueue } from '../backendReadyQueue';

const tick = () => new Promise<void>((resolve) => setTimeout(resolve, 0));

describe('createBackendReadyQueue', () => {
  it('holds tasks until flush and exposes pending size', async () => {
    const queue = createBackendReadyQueue();
    const task = vi.fn(async () => 'done');

    const pending = queue.enqueue(task, 'list_sessions');
    await tick();

    expect(task).not.toHaveBeenCalled();
    expect(queue.size()).toBe(1);

    queue.flush();
    await expect(pending).resolves.toBe('done');
    expect(task).toHaveBeenCalledTimes(1);
    expect(queue.size()).toBe(0);
  });

  it('flushes tasks in FIFO order', async () => {
    const queue = createBackendReadyQueue();
    const order: string[] = [];
    const make = (name: string) => async () => {
      order.push(name);
      return name;
    };

    const a = queue.enqueue(make('a'), 'a');
    const b = queue.enqueue(make('b'), 'b');
    const c = queue.enqueue(make('c'), 'c');
    queue.flush();

    await Promise.all([a, b, c]);
    expect(order).toEqual(['a', 'b', 'c']);
  });

  it('propagates task failures to the caller without breaking the queue', async () => {
    const queue = createBackendReadyQueue();
    const boom = queue.enqueue(async () => {
      throw new Error('backend 500');
    }, 'boom');
    const ok = queue.enqueue(async () => 'fine', 'ok');

    queue.flush();

    await expect(boom).rejects.toThrow('backend 500');
    await expect(ok).resolves.toBe('fine');
  });

  it('treats flush as an idempotent drain (second flush is a no-op)', async () => {
    const queue = createBackendReadyQueue();
    const task = vi.fn(async () => 1);

    const pending = queue.enqueue(task, 'once');
    queue.flush();
    queue.flush();

    await pending;
    expect(task).toHaveBeenCalledTimes(1);
  });

  it('accepts new tasks after a flush for the next readiness window', async () => {
    const queue = createBackendReadyQueue();
    const first = queue.enqueue(async () => 'first', 'first');
    queue.flush();
    await first;

    const second = queue.enqueue(async () => 'second', 'second');
    expect(queue.size()).toBe(1);
    queue.flush();
    await expect(second).resolves.toBe('second');
  });

  it('rejects every pending task on rejectAll and never runs them', async () => {
    const queue = createBackendReadyQueue();
    const task = vi.fn(async () => 'never');
    const pending = queue.enqueue(task, 'pending');

    const reason = new BackendNotReadyError();
    queue.rejectAll(reason);

    await expect(pending).rejects.toBe(reason);
    expect(task).not.toHaveBeenCalled();
    expect(queue.size()).toBe(0);
  });

  it('rejects new tasks immediately when maxSize is exceeded', async () => {
    const onOverflow = vi.fn();
    const queue = createBackendReadyQueue({ maxSize: 1, onOverflow });

    const held = queue.enqueue(async () => 'held', 'first');
    const overflowed = queue.enqueue(async () => 'overflow', 'second');

    await expect(overflowed).rejects.toBeInstanceOf(BackendNotReadyError);
    expect(onOverflow).toHaveBeenCalledWith('second');
    expect(queue.size()).toBe(1);

    queue.flush();
    await expect(held).resolves.toBe('held');
  });
});
