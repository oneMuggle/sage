/**
 * chatApi — Task 8 RED tests for `orchestrationMode` plumbing in `chatStream`.
 * Validates:
 *   - orchestrationMode forwarded into the `agent_chat_stream` invoke body
 *   - undefined orchestrationMode serialises as null (aligned `?? null` pattern)
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';

const mockInvoke = vi.fn();
const mockListen = vi.fn();

vi.mock('../desktopInvoke', () => ({
  invoke: (...args: unknown[]) => mockInvoke(...args),
}));

vi.mock('../desktopEvent', () => ({
  listen: (...args: unknown[]) => mockListen(...args),
}));

import { chatApi } from '../chatApi';

const SESSION_ID = '12345678-1234-1234-1234-1234567890ab';
const MESSAGE = 'hello world';
const BASE_HANDLERS = {
  onEvent: vi.fn(),
  onError: vi.fn(),
  onDone: vi.fn(),
};

beforeEach(() => {
  mockInvoke.mockReset();
  mockListen.mockReset();
  mockInvoke.mockResolvedValue({ streamId: 'stream-1' });
  mockListen.mockResolvedValue(() => undefined);
});

describe('chatApi.chatStream — orchestrationMode (Task 8)', () => {
  it('passes orchestrationMode through to invoke', async () => {
    await chatApi.chatStream(SESSION_ID, MESSAGE, BASE_HANDLERS, {
      orchestrationMode: 'force_multi',
    });
    expect(mockInvoke).toHaveBeenCalledWith(
      'agent_chat_stream',
      expect.objectContaining({ orchestrationMode: 'force_multi' }),
    );
  });

  it('passes null orchestrationMode when undefined', async () => {
    await chatApi.chatStream(SESSION_ID, MESSAGE, BASE_HANDLERS, {});
    expect(mockInvoke).toHaveBeenCalledWith(
      'agent_chat_stream',
      expect.objectContaining({ orchestrationMode: null }),
    );
  });
});
