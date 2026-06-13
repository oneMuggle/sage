/**
 * agentsApi 测试 (PR-5)
 *
 * 策略:mock `@tauri-apps/api/core` 的 invoke (通过 lib/desktopInvoke shim),
 * 验证 agentsApi.toggle / update / list 三个方法传给 invoke 的契约:
 *
 *  1. 命令名正确 (list_agents / toggle_agent / update_agent)
 *  2. 参数对象结构正确 (toggle: { id, enabled }; update: { id, update })
 *  3. 返回值类型正确 (toggle/update 返回 AgentProfile, list 返回 array)
 *  4. update 不会塞入整 AgentProfile (PR-4 契约修复回归)
 *
 * 注: 重试行为由 withRetry helper 自身负责测试, 本文件聚焦 agentsApi
 * 与 invoke 的契约。
 *
 * 与后端契约对齐:
 *  - tests/integration/test_routes_agents_toggle.py
 *  - tests/integration/test_routes_agents_update.py
 *  - tests/integration/test_routes_agents.py
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const invokeMock = vi.fn();
vi.mock('../../../lib/desktopInvoke', () => ({
  invoke: (...args: unknown[]) => invokeMock(...args),
}));

// Import after mock setup so the shim is replaced.
import { agentsApi, type AgentProfile, type AgentUpdate } from '../../../lib/api';

const SAMPLE_AGENT: AgentProfile = {
  id: 'coder',
  name: 'Coder',
  role: 'coder',
  description: 'desc',
  system_prompt: 'sys',
  tools: ['file_read'],
  memory_access: ['semantic'],
  model_config: { model: 'gpt-4', temperature: 0.3, max_tokens: 4096 },
  max_iterations: 15,
  enabled: true,
  updated_at: 1_700_000_000_000,
};

beforeEach(() => {
  invokeMock.mockReset();
});

afterEach(() => {
  invokeMock.mockReset();
});

describe('agentsApi.list', () => {
  it('调用 list_agents 命令, 无参数, 返回 AgentProfile 数组', async () => {
    invokeMock.mockResolvedValueOnce([SAMPLE_AGENT]);

    const result = await agentsApi.list();

    expect(invokeMock).toHaveBeenCalledWith('list_agents');
    expect(result).toEqual([SAMPLE_AGENT]);
  });
});

describe('agentsApi.toggle', () => {
  it('调用 toggle_agent 命令, 传 { id, enabled } 对象', async () => {
    invokeMock.mockResolvedValueOnce({ ...SAMPLE_AGENT, enabled: false });

    const result = await agentsApi.toggle('coder', false);

    expect(invokeMock).toHaveBeenCalledTimes(1);
    expect(invokeMock).toHaveBeenCalledWith('toggle_agent', { id: 'coder', enabled: false });
    expect(result.enabled).toBe(false);
    expect(result.id).toBe('coder');
  });

  it('enable=true 和 false 都正确传给 invoke', async () => {
    invokeMock.mockResolvedValueOnce({ ...SAMPLE_AGENT, enabled: true });
    await agentsApi.toggle('primary', true);
    expect(invokeMock).toHaveBeenLastCalledWith('toggle_agent', {
      id: 'primary',
      enabled: true,
    });

    invokeMock.mockResolvedValueOnce({ ...SAMPLE_AGENT, enabled: false });
    await agentsApi.toggle('primary', false);
    expect(invokeMock).toHaveBeenLastCalledWith('toggle_agent', {
      id: 'primary',
      enabled: false,
    });
  });

  it('返回完整的 AgentProfile (含 updated_at), 不丢字段', async () => {
    const updated: AgentProfile = {
      ...SAMPLE_AGENT,
      enabled: false,
      updated_at: 1_700_000_999_999,
    };
    invokeMock.mockResolvedValueOnce(updated);

    const result = await agentsApi.toggle('coder', false);

    expect(result).toEqual(updated);
  });
});

describe('agentsApi.update', () => {
  it('调用 update_agent 命令, 传 { id, update } 对象 (不是整 AgentProfile)', async () => {
    invokeMock.mockResolvedValueOnce({ ...SAMPLE_AGENT, name: '新代码工匠' });

    const partial: AgentUpdate = { name: '新代码工匠' };
    const result = await agentsApi.update('coder', partial);

    expect(invokeMock).toHaveBeenCalledTimes(1);
    expect(invokeMock).toHaveBeenCalledWith('update_agent', {
      id: 'coder',
      update: partial,
    });
    expect(result.name).toBe('新代码工匠');
  });

  it('不会把整 AgentProfile 当 update 参数 (PR-4 契约回归)', async () => {
    invokeMock.mockResolvedValueOnce(SAMPLE_AGENT);

    // 故意只传部分字段
    await agentsApi.update('coder', { max_iterations: 25 });

    const [, payload] = invokeMock.mock.calls[0];
    expect(payload).toHaveProperty('id');
    expect(payload).toHaveProperty('update');
    // 关键断言: payload 不应包含整 AgentProfile 字段 (id 仅在外层, 不在 update 里)
    expect(payload).not.toHaveProperty('agent');
    const update = (payload as { update: Record<string, unknown> }).update;
    expect(update).not.toHaveProperty('id'); // id 不在 update 里, 在外层
    expect(update).not.toHaveProperty('updated_at');
  });

  it('多字段 update 完整透传', async () => {
    invokeMock.mockResolvedValueOnce(SAMPLE_AGENT);

    const update: AgentUpdate = {
      name: 'X',
      max_iterations: 20,
      description: '新描述',
      enabled: false,
    };
    await agentsApi.update('researcher', update);

    expect(invokeMock).toHaveBeenCalledWith('update_agent', {
      id: 'researcher',
      update,
    });
  });

  it('返回完整的 AgentProfile (后端返回的最新状态)', async () => {
    const updated: AgentProfile = { ...SAMPLE_AGENT, description: '新', updated_at: 99 };
    invokeMock.mockResolvedValueOnce(updated);

    const result = await agentsApi.update('coder', { description: '新' });

    expect(result).toEqual(updated);
  });
});
