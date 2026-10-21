/**
 * r90: agentsApi 单元测试——list/toggle/update/create 通道与错误包装。
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';

const mockInvoke = vi.fn();

vi.mock('../desktopInvoke', () => ({
  invoke: (...args: unknown[]) => mockInvoke(...args),
}));

import { agentsApi } from '../agentsApi';
import type { AgentProfile } from '../types';

const AGENT: AgentProfile = {
  id: 'agent-1',
  name: 'coordinator',
  role: 'coordinator',
  enabled: true,
  description: '',
  max_iterations: 5,
  created_at: 1,
  updated_at: 1,
} as unknown as AgentProfile;

beforeEach(() => {
  mockInvoke.mockReset();
});

describe('agentsApi', () => {
  it('list() invokes list_agents and returns profiles', async () => {
    mockInvoke.mockResolvedValueOnce([AGENT]);
    const r = await agentsApi.list();
    expect(mockInvoke).toHaveBeenCalledWith('list_agents');
    expect(r[0].id).toBe('agent-1');
  });

  it('toggle() passes id and enabled', async () => {
    mockInvoke.mockResolvedValueOnce({ ...AGENT, enabled: false });
    const r = await agentsApi.toggle('agent-1', false);
    expect(mockInvoke).toHaveBeenCalledWith('toggle_agent', { id: 'agent-1', enabled: false });
    expect(r.enabled).toBe(false);
  });

  it('update() passes diff payload (not whole profile)', async () => {
    mockInvoke.mockResolvedValueOnce({ ...AGENT, name: '新名' });
    const r = await agentsApi.update('agent-1', { name: '新名' });
    expect(mockInvoke).toHaveBeenCalledWith('update_agent', { id: 'agent-1', update: { name: '新名' } });
    expect(r.name).toBe('新名');
  });

  it('create() passes payload through as bridge keys', async () => {
    mockInvoke.mockResolvedValueOnce(AGENT);
    const payload = { name: 'coder-2', role: 'coder', max_iterations: 10 };
    const r = await agentsApi.create(payload as never);
    expect(mockInvoke).toHaveBeenCalledWith('create_agent', payload);
    expect(r.role).toBe('coordinator');
  });

  it('wraps rejection after retries (fake timers)', async () => {
    vi.useFakeTimers();
    try {
      mockInvoke.mockRejectedValue(new Error('agent not found'));
      const p = agentsApi.toggle('agent-1', true);
      const settled = p.then(
        (v) => ({ ok: true as const, v }),
        (e: unknown) => ({ ok: false as const, e }),
      );
      // withRetry: 1s + 2s + 4s 退避
      await vi.advanceTimersByTimeAsync(8_000);
      const r = await settled;
      expect(r.ok).toBe(false);
      expect(mockInvoke).toHaveBeenCalledTimes(4);
    } finally {
      vi.useRealTimers();
    }
  });
});
