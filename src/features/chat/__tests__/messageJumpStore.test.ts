// 对话阅读导航 A1: 定位请求通道（登记 / 消费 / TTL 过期）。
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { MESSAGE_JUMP_TTL_MS, requestMessageJump, useMessageJumpStore } from '../messageJumpStore';

describe('messageJumpStore', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    useMessageJumpStore.setState({ pending: null });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('registers a request with a fresh nonce each time', () => {
    const first = requestMessageJump({ messageId: 'm1' });
    const second = requestMessageJump({ messageId: 'm1' });
    expect(second).toBeGreaterThan(first);
    expect(useMessageJumpStore.getState().pending).toEqual({ messageId: 'm1', nonce: second });
  });

  it('keeps heading hints on the pending request', () => {
    requestMessageJump({ messageId: 'm2', headingText: '背景', headingIndex: 1 });
    expect(useMessageJumpStore.getState().pending).toMatchObject({
      messageId: 'm2',
      headingText: '背景',
      headingIndex: 1,
    });
  });

  it('consume clears only the matching nonce', () => {
    const stale = requestMessageJump({ messageId: 'm1' });
    const fresh = requestMessageJump({ messageId: 'm2' });
    useMessageJumpStore.getState().consume(stale);
    expect(useMessageJumpStore.getState().pending?.messageId).toBe('m2');
    useMessageJumpStore.getState().consume(fresh);
    expect(useMessageJumpStore.getState().pending).toBeNull();
  });

  it('expires an unconsumed request after the TTL without clobbering a newer one', () => {
    requestMessageJump({ messageId: 'm1' });
    vi.advanceTimersByTime(MESSAGE_JUMP_TTL_MS - 1000);
    const newer = requestMessageJump({ messageId: 'm2' });
    // 第一条的 TTL 到期：不得清掉更新的请求
    vi.advanceTimersByTime(1000);
    expect(useMessageJumpStore.getState().pending?.nonce).toBe(newer);
    vi.advanceTimersByTime(MESSAGE_JUMP_TTL_MS);
    expect(useMessageJumpStore.getState().pending).toBeNull();
  });
});
