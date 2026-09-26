// 对话阅读体验第二轮：chatApi 的端点可达性上报（C3）与原位重新生成透传（C2）。
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { useEndpointStatusStore } from '../../lib/endpointStatus';
import { chatApi } from '../chatApi';
import type { AgentEvent } from '../types';

const listen = vi.fn();
const invoke = vi.fn();
vi.mock('../desktopEvent', () => ({ listen: (...args: unknown[]) => listen(...args) }));
vi.mock('../desktopInvoke', () => ({ invoke: (...args: unknown[]) => invoke(...args) }));

const SESSION_ID = '11111111-2222-3333-4444-555555555555';
const CONFIG = { apiUrl: 'https://api.example.com/v1', model: 'gpt-test', regenerateOf: 'u-1' };

function streamWith(payload: Partial<AgentEvent>) {
  listen.mockImplementationOnce(async (_name, cb) => {
    cb({ payload });
    return vi.fn();
  });
  return chatApi.chatStream(SESSION_ID, 'hello', { onEvent: vi.fn(), onError: vi.fn() }, CONFIG);
}

beforeEach(() => {
  listen.mockReset();
  invoke.mockReset();
  invoke.mockResolvedValue({ streamId: 'stream' });
  useEndpointStatusStore.setState({ issue: null, dismissed: false });
});

describe('chatApi.chatStream — reading round 2', () => {
  it('reports an unreachable endpoint when the stream fails with a network error', async () => {
    await streamWith({
      state: 'failed',
      error: { type: 'network_error', message: 'connect failed' },
    });
    expect(useEndpointStatusStore.getState().issue).toMatchObject({
      kind: 'network',
      host: 'api.example.com',
      model: 'gpt-test',
    });
  });

  it('clears the endpoint notice after a successful run', async () => {
    await streamWith({ state: 'failed', error: { type: 'timeout', message: 't' } });
    expect(useEndpointStatusStore.getState().issue).not.toBeNull();
    await streamWith({ state: 'done', content: 'ok' });
    expect(useEndpointStatusStore.getState().issue).toBeNull();
  });

  it('forwards the in-place regenerate anchor to the backend', async () => {
    await streamWith({ state: 'done', content: 'ok' });
    expect(invoke).toHaveBeenCalledWith(
      'agent_chat_stream',
      expect.objectContaining({ regenerateOf: 'u-1', sessionId: SESSION_ID }),
    );
  });
});
