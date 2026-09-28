/**
 * fakeStream 夹具自测。
 *
 * 夹具本身是测试基建 —— 一旦它坏了，**用它写的所有测试都会静默变空**
 * （回调不触发 → 断言"没变化"→ 假绿）。所以夹具需要自己的测试。
 */
import { describe, expect, it } from 'vitest';

import { contentDelta, createFakeStream, done, scriptStream, streamEvent } from './fakeStream';

/** 手工接管 listen 拿到的回调，并返回 unlisten 句柄。 */
async function attach(stream: ReturnType<typeof createFakeStream>) {
  const received: unknown[] = [];
  const unlisten = (await stream.listen('chat:stream-event', (e: unknown) =>
    received.push(e),
  )) as () => void;
  return { received, unlisten };
}

describe('fakeStream — microtask 模式', () => {
  it('在 listen 返回前按序发完全部事件', async () => {
    const stream = createFakeStream([contentDelta('a'), contentDelta('b'), done('ab', 1)]);
    const received: unknown[] = [];
    const ready = stream.listen('chat:stream-event', (e: unknown) => received.push(e));
    expect(received).toHaveLength(0); // 尚未 await → 还没发

    await ready;
    expect(received).toHaveLength(3);
    expect(received[0]).toEqual(contentDelta('a'));
    expect(received[2]).toEqual(done('ab', 1));
  });

  it('发完即关流（unlistenCalled）', async () => {
    const stream = createFakeStream([done('x')]);
    await attach(stream);
    expect(stream.unlistenCalled()).toBe(true);
  });

  it('closeWhenDone=false 时发完仍保持订阅', async () => {
    const stream = createFakeStream([done('x')], { closeWhenDone: false });
    await attach(stream);
    expect(stream.unlistenCalled()).toBe(false);
    expect(stream.emitted()).toBe(1);
  });
});

describe('fakeStream — manual 模式', () => {
  it('emitNext 逐条投递，发完返回 false', async () => {
    const stream = createFakeStream([contentDelta('a'), contentDelta('b'), done('ab')], {
      step: 'manual',
    });
    const { received } = await attach(stream);
    expect(received).toHaveLength(0); // listen 不自行投递

    expect(stream.emitNext()).toBe(true);
    expect(received).toEqual([contentDelta('a')]);
    expect(stream.emitNext()).toBe(true);
    expect(stream.emitNext()).toBe(true);
    expect(stream.emitted()).toBe(3);
    expect(stream.unlistenCalled()).toBe(true);

    expect(stream.emitNext()).toBe(false); // 已发完，不再补投
    expect(received).toHaveLength(3);
  });

  it('emitAll 一次投完剩余', async () => {
    const stream = createFakeStream([contentDelta('a'), contentDelta('b'), done('ab')], {
      step: 'manual',
    });
    await attach(stream);
    stream.emitAll();
    expect(stream.emitted()).toBe(3);
    expect(stream.unlistenCalled()).toBe(true);
  });

  it('调用方主动取消订阅后 emitAll 不再投递', async () => {
    const stream = createFakeStream([contentDelta('a'), contentDelta('b')], { step: 'manual' });
    const { received, unlisten } = await attach(stream);

    unlisten(); // 组件卸载路径
    expect(stream.unlistenCalled()).toBe(true);

    stream.emitAll();
    expect(stream.emitted()).toBe(2); // 队列走完
    expect(received).toHaveLength(0); // 但 listener 已置 null，一条也没到
  });
});

describe('scriptStream', () => {
  it('拼接 chunks 并以 joined 文本收尾', async () => {
    const stream = scriptStream(['he', 'llo']);
    const { received } = await attach(stream);
    expect(stream.emitted()).toBe(3);
    expect(received[2]).toEqual(done('hello', 0));
  });

  it('finalContent 覆盖收尾内容', async () => {
    const stream = scriptStream(['he', 'llo'], { finalContent: 'hello!', step: 'manual' });
    const { received } = await attach(stream);
    stream.emitAll();
    expect(received[2]).toEqual(done('hello!', 0));
  });
});

describe('streamEvent', () => {
  it('state 必填、其余按需覆盖', () => {
    expect(streamEvent('failed', { error: 'boom' })).toEqual({
      payload: { state: 'failed', error: 'boom' },
    });
  });
});
