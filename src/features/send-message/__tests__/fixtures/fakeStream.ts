/**
 * 流式事件测试夹具 —— 消除各处手工 `listenMock.mockImplementationOnce` 的重复。
 *
 * 现状：useChat / chatStreamStore 的 5 个测试文件各自手写一份
 * ```ts
 * listenMock.mockImplementationOnce(async (_name, cb) => {
 *   Promise.resolve().then(() => cb({ payload: { state: 'done', iteration: 1, content: '...' } }));
 *   return vi.fn();
 * });
 * ```
 * 事件形状一旦演进（加字段 / 改 state 名），5 处要同步改，且没人保证改全。
 *
 * 本模块把「事件构造」与「投递节奏」分开：
 * - 构造函数（`contentDelta` / `done` / ...）只管形状，字段名与 useChat 的
 *   `evt.state` 分派一一对应；
 * - `createFakeStream` 只管投递，可选 microtask（默认）或 manual —— manual
 *   让测试自己控制"什么时候来下一个 delta"，用于验证逐 token 行为
 *   （如 P0-2 的滚动合帧）。
 *
 * 不发起任何真实 IPC：调用方自己把它接到 `desktopEvent.listen` 的 mock 上。
 */
import { vi, type Mock } from 'vitest';

/** useChat 事件回调收到的信封。字段用 index signature —— 各 state 载荷不同。 */
export interface StreamEnvelope {
  payload: StreamPayload;
  [key: string]: unknown;
}

export interface StreamPayload {
  state: string;
  iteration?: number;
  step_index?: number | null;
  content?: string;
  reasoning?: string;
  error?: string;
  tool_call?: { name?: string; arguments?: unknown; id?: string };
  tool_result?: unknown;
  [key: string]: unknown;
}

/** 建一条流事件。`state` 必填，其余按需覆盖。 */
export function streamEvent(state: string, overrides: Partial<StreamPayload> = {}): StreamEnvelope {
  return { payload: { state, ...overrides } };
}

/** 助手正文增量 —— useChat 走 `evt.state === 'content_delta' && evt.content` 分支。 */
export function contentDelta(content: string, iteration = 0): StreamEnvelope {
  return streamEvent('content_delta', { content, iteration });
}

/** 思考过程增量。 */
export function reasoningDelta(reasoning: string, iteration = 0): StreamEnvelope {
  return streamEvent('reasoning_delta', { reasoning, iteration });
}

/** 回合结束。`content` 缺省时 useChat 保留已累积的正文。 */
export function done(content?: string, iteration = 0): StreamEnvelope {
  return streamEvent('done', content === undefined ? { iteration } : { iteration, content });
}

/** 回合失败。 */
export function failed(error: string, iteration = 0): StreamEnvelope {
  return streamEvent('failed', { error, iteration });
}

/** 工具调用。 */
export function acting(toolCall: StreamPayload['tool_call'], iteration = 0): StreamEnvelope {
  return streamEvent('acting', { tool_call: toolCall, iteration });
}

export interface FakeStream {
  /** listen 的 mock 实现，直接 `listenMock.mockImplementation(stream.listen)`。 */
  listen: Mock;
  /** 手动模式下投递下一条；已投递完返回 false。 */
  emitNext: () => boolean;
  /** 投递剩余全部。 */
  emitAll: () => void;
  /** 已投递条数。 */
  emitted: () => number;
  /** unlisten 是否已被调用（流关闭或调用方取消订阅都会置位）。 */
  unlistenCalled: () => boolean;
}

export interface FakeStreamOptions {
  /**
   * 投递节奏：
   * - `'microtask'`（默认）—— listen resolve 前把全部事件按序发完，
   *   等价于现有测试的手写写法；
   * - `'manual'` —— 只在 `emitNext()` / `emitAll()` 时投递，让测试能卡在
   *   两个 delta 之间。
   */
  step?: 'microtask' | 'manual';
  /** 事件全部发完后是否自动关闭流（模拟后端推完即断）。 */
  closeWhenDone?: boolean;
}

/**
 * 造一个脚本化的流 mock。
 *
 * ```ts
 * const stream = createFakeStream([contentDelta('hi'), done('hi')]);
 * listenMock.mockImplementation(stream.listen);
 * ```
 */
export function createFakeStream(
  events: StreamEnvelope[],
  options: FakeStreamOptions = {},
): FakeStream {
  const { step = 'microtask', closeWhenDone = true } = options;
  const queue = [...events];
  let index = 0;
  let unlistenCalled = false;
  let listener: ((e: StreamEnvelope) => void) | null = null;

  const deliver = (envelope: StreamEnvelope) => {
    index += 1;
    listener?.(envelope);
    if (closeWhenDone && index >= queue.length) {
      unlistenCalled = true;
      listener = null;
    }
  };

  const listen = vi.fn(async (_channel: string, cb: (e: StreamEnvelope) => void) => {
    listener = cb;
    if (step === 'microtask') {
      // 微观队列逐条发：与 useChat 的 zustand state setter 交替推进，
      // 不会像同步连发那样把 React 更新批成一次。
      for (let i = index; i < queue.length; i += 1) {
        await Promise.resolve();
        if (listener === null) break; // 已关流
        deliver(queue[i]);
      }
    }
    return () => {
      unlistenCalled = true;
      listener = null;
    };
  });

  return {
    listen,
    emitNext: () => {
      if (index >= queue.length) return false;
      deliver(queue[index]);
      return true;
    },
    emitAll: () => {
      while (index < queue.length) {
        deliver(queue[index]);
      }
    },
    emitted: () => index,
    unlistenCalled: () => unlistenCalled,
  };
}

/** 便捷组合：若干正文增量 + 一次 done。 */
export function scriptStream(
  chunks: string[],
  options: { iteration?: number; finalContent?: string; step?: FakeStreamOptions['step'] } = {},
): FakeStream {
  const { iteration = 0, finalContent, step } = options;
  const events = chunks.map((chunk) => contentDelta(chunk, iteration));
  events.push(done(finalContent ?? chunks.join(''), iteration));
  return createFakeStream(events, step ? { step } : {});
}
