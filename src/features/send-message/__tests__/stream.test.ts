/**
 * chatApi.chatStream (PR-6) 单元测试
 *
 * 策略: mock shared/api/desktopInvoke 的 invoke 和 shared/api/desktopEvent 的 listen,
 * 验证 NDJSON → Tauri event 的契约:
 *   1. invoke('agent_chat_stream', {sessionId, message, ...config}) 返回 streamId
 *   2. listen('chat-stream-{streamId}', cb) 订阅事件
 *   3. listen 回调收到 payload → onEvent 被调
 *   4. state='done' → onDone 被调, cancel() 内部 unlisten
 *   5. state='failed' + error → onError 被调, onDone 也被调
 *   6. listen 失败 → chatStream reject 抛 STREAM_LISTEN_FAILED
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { chatApi, type AgentEvent } from '../../../shared/api/api';

const invokeMock = vi.fn();
const listenMock = vi.fn();

vi.mock('../../../shared/api/desktopInvoke', () => ({
  invoke: (...args: unknown[]) => invokeMock(...args),
}));

vi.mock('../../../shared/api/desktopEvent', () => ({
  listen: (...args: unknown[]) => listenMock(...args),
}));

const VALID_SESSION_ID = '11111111-2222-3333-4444-555555555555';

type ListenCallback = (event: { payload: AgentEvent }) => void;

describe('chatApi.chatStream (PR-6)', () => {
  beforeEach(() => {
    invokeMock.mockReset();
    listenMock.mockReset();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it('invokes agent_chat_stream then listens on chat-stream-{id}', async () => {
    const streamId = 'stream-abc-123';
    // 后端真实返回: { streamId: "..." } 对象,不是裸 string
    invokeMock.mockResolvedValueOnce({ streamId });
    listenMock.mockResolvedValueOnce(vi.fn());

    const result = await chatApi.chatStream(
      VALID_SESSION_ID,
      'hello',
      { onEvent: vi.fn() },
      {
        apiKey: 'sk-test',
        apiUrl: 'https://api.test/v1',
        model: 'gpt-x',
        maxContext: 8192,
        temperature: 0.7,
      },
    );

    // 1) invoke 拿到 stream_id
    expect(invokeMock).toHaveBeenCalledWith('agent_chat_stream', {
      sessionId: VALID_SESSION_ID,
      message: 'hello',
      apiKey: 'sk-test',
      apiUrl: 'https://api.test/v1',
      model: 'gpt-x',
      maxContext: 8192,
      temperature: 0.7,
    });
    // 2) listen 订阅 chat-stream-{id} (从 {streamId} 对象解构得到)
    expect(listenMock).toHaveBeenCalledWith(`chat-stream-${streamId}`, expect.any(Function));
    // 3) 返回 streamId + cancel
    expect(result.streamId).toBe(streamId);
    expect(typeof result.cancel).toBe('function');
  });

  it('dispatches AgentEvent to onEvent callback', async () => {
    const streamId = 'stream-evt';
    invokeMock.mockResolvedValueOnce({ streamId });
    let listenCb: ListenCallback | null = null;
    listenMock.mockImplementationOnce(async (_name: string, cb: ListenCallback) => {
      listenCb = cb;
      return vi.fn();
    });

    const onEvent = vi.fn();
    await chatApi.chatStream(VALID_SESSION_ID, 'hi', { onEvent });

    const payload: AgentEvent = {
      state: 'thinking',
      iteration: 0,
    };
    listenCb!({ payload });

    expect(onEvent).toHaveBeenCalledWith(payload);
  });

  it('calls onDone on state=done and cancel() is a no-op after', async () => {
    const streamId = 'stream-done';
    invokeMock.mockResolvedValueOnce({ streamId });
    let listenCb: ListenCallback | null = null;
    listenMock.mockImplementationOnce(async (_name: string, cb: ListenCallback) => {
      listenCb = cb;
      return vi.fn();
    });

    const onEvent = vi.fn();
    const onDone = vi.fn();
    const { cancel } = await chatApi.chatStream(VALID_SESSION_ID, 'q', {
      onEvent,
      onDone,
    });

    listenCb!({
      payload: { state: 'done', iteration: 1, content: 'answer' },
    });

    expect(onEvent).toHaveBeenCalledTimes(1);
    expect(onDone).toHaveBeenCalledTimes(1);
    // done 后 cancel() 不抛错 (内部已 unlisten 过一次)
    expect(() => cancel()).not.toThrow();
  });

  it('calls onError + onDone on state=failed with error', async () => {
    const streamId = 'stream-fail';
    invokeMock.mockResolvedValueOnce({ streamId });
    let listenCb: ListenCallback | null = null;
    listenMock.mockImplementationOnce(async (_name: string, cb: ListenCallback) => {
      listenCb = cb;
      return vi.fn();
    });

    const onError = vi.fn();
    const onDone = vi.fn();
    await chatApi.chatStream(VALID_SESSION_ID, 'q', {
      onEvent: vi.fn(),
      onError,
      onDone,
    });

    listenCb!({
      payload: { state: 'failed', iteration: 0, error: 'LLM timeout' },
    });

    expect(onError).toHaveBeenCalledWith(expect.any(Error));
    expect((onError.mock.calls[0][0] as Error).message).toBe('LLM timeout');
    expect(onDone).toHaveBeenCalledTimes(1);
  });

  it('rejects with STREAM_LISTEN_FAILED when listen throws', async () => {
    invokeMock.mockResolvedValueOnce({ streamId: 'stream-x' });
    listenMock.mockRejectedValueOnce(new Error('event subscribe failed'));

    await expect(
      chatApi.chatStream(VALID_SESSION_ID, 'q', { onEvent: vi.fn() }),
    ).rejects.toMatchObject({ code: 'STREAM_LISTEN_FAILED' });
  });

  it('rejects with VALIDATION_ERROR for bad sessionId', async () => {
    await expect(chatApi.chatStream('not-a-uuid', 'q', { onEvent: vi.fn() })).rejects.toMatchObject(
      { code: 'VALIDATION_ERROR' },
    );
    expect(invokeMock).not.toHaveBeenCalled();
  });

  // I5: 流式 producer 把 done.content 拆成 content_delta chunks,
  // 每个 chunk 触发 onEvent 但不应触发 onDone — onDone 由最终的 done 事件触发。
  // 这一不变性保证前端能累积所有 chunk,然后才完成流。
  it('content_delta events do NOT trigger onDone (only final done does)', async () => {
    const streamId = 'stream-deltas';
    invokeMock.mockResolvedValueOnce({ streamId });
    let listenCb: ListenCallback | null = null;
    listenMock.mockImplementationOnce(async (_name: string, cb: ListenCallback) => {
      listenCb = cb;
      return vi.fn();
    });

    const onEvent = vi.fn();
    const onDone = vi.fn();
    const { cancel } = await chatApi.chatStream(VALID_SESSION_ID, 'q', {
      onEvent,
      onDone,
    });

    // 派发 3 个 content_delta chunks + 1 个 done
    listenCb!({ payload: { state: 'content_delta', iteration: 0, content: '答' } });
    listenCb!({ payload: { state: 'content_delta', iteration: 0, content: '案是' } });
    listenCb!({ payload: { state: 'content_delta', iteration: 0, content: ' 2' } });
    listenCb!({ payload: { state: 'done', iteration: 1, content: '答案是 2' } });

    // 4 个事件全部走到 onEvent
    expect(onEvent).toHaveBeenCalledTimes(4);
    // onDone 只在最终 done 触发一次
    expect(onDone).toHaveBeenCalledTimes(1);
    // cancel() 在 done 后是 no-op (不抛错)
    expect(() => cancel()).not.toThrow();
  });
});
