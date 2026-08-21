/**
 * chatApi.interrupt — P0-2: streamId 透传到 invoke body。
 * Electron relay 的 camelToSnakeKeys 会把 { streamId } 转成 { stream_id }。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mockInvoke = vi.fn();
const mockListen = vi.fn();

vi.mock('../desktopInvoke', () => ({
  invoke: (...args: unknown[]) => mockInvoke(...args),
}));

vi.mock('../desktopEvent', () => ({
  listen: (...args: unknown[]) => mockListen(...args),
}));

import { chatApi } from '../chatApi';

beforeEach(() => {
  mockInvoke.mockReset();
  mockListen.mockReset();
  mockInvoke.mockResolvedValue(undefined);
});

describe('chatApi.interrupt (P0-2)', () => {
  it('forwards streamId into invoke args', async () => {
    await chatApi.interrupt('stream-42');
    expect(mockInvoke).toHaveBeenCalledWith('interrupt_agent', { streamId: 'stream-42' });
  });

  it('sends empty body when streamId omitted (backward compat)', async () => {
    await chatApi.interrupt();
    expect(mockInvoke).toHaveBeenCalledWith('interrupt_agent', {});
  });

  it('swallows invoke errors', async () => {
    mockInvoke.mockRejectedValueOnce(new Error('boom'));
    await expect(chatApi.interrupt('s1')).resolves.toBeUndefined();
  });
});
