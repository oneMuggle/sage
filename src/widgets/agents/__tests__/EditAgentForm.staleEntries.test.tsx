/**
 * R107: 白名单未发布插件条目的可见化与就地移除（纯前端标注）。
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { AgentProfile } from '../../../shared/api';
import { EditAgentForm } from '../EditAgentForm';

const runtimeTools = vi.fn();
const listPlugins = vi.fn();

vi.mock('../../../shared/api/pluginClient', async () => {
  const actual = await vi.importActual<typeof import('../../../shared/api/pluginClient')>(
    '../../../shared/api/pluginClient',
  );
  return {
    ...actual,
    pluginClient: {
      ...actual.pluginClient,
      runtimeTools: (...a: unknown[]) => runtimeTools(...a),
      list: (...a: unknown[]) => listPlugins(...a),
    },
  };
});

function makeAgent(tools: string[]): AgentProfile {
  return {
    id: 'agent-1',
    name: '测试 Agent',
    role: 'tester',
    description: '',
    system_prompt: '',
    tools,
    memory_access: [],
    model_config: { model: 'test-model', temperature: 0.5, max_tokens: 1024 },
    max_iterations: 10,
    enabled: true,
  };
}

const renderForm = (agent: AgentProfile, onChange = vi.fn()) =>
  render(<EditAgentForm agent={agent} form={{}} onChange={onChange} onSave={vi.fn()} onCancel={vi.fn()} />);

beforeEach(() => {
  runtimeTools.mockReset().mockResolvedValue([
    {
      plugin_name: 'demo',
      capability_name: 'hello',
      tool_name: 'plugin__demo__hello',
      description: '',
      risk: 'low',
      permissions: [],
    },
  ]);
  listPlugins.mockReset().mockResolvedValue([
    { name: 'demo', status: 'enabled' },
    { name: 'gone', status: 'uninstalled' },
  ]);
});

describe('EditAgentForm stale plugin entries (R107)', () => {
  it('annotates unpublished plugin entries and removes one into the draft', async () => {
    const onChange = vi.fn();
    const agent = makeAgent([
      'read_file',
      'plugin__demo__hello',
      'plugin__demo__other',
      'plugin__gone__*',
      'plugin__ghost__run',
    ]);
    renderForm(agent, onChange);

    expect(await screen.findByTestId('agent-stale-plugin-entries')).toBeInTheDocument();
    expect(screen.getAllByTestId('agent-stale-plugin-entry')).toHaveLength(3);
    expect(screen.getByTestId('agent-stale-plugin-status-plugin__demo__other').textContent).toBe(
      '当前未发布',
    );
    expect(screen.getByTestId('agent-stale-plugin-status-plugin__gone__*').textContent).toBe(
      '插件已已卸载',
    );
    expect(screen.getByTestId('agent-stale-plugin-status-plugin__ghost__run').textContent).toBe(
      '插件无记录',
    );

    fireEvent.click(screen.getByTestId('agent-stale-plugin-remove-plugin__ghost__run'));

    await waitFor(() => expect(screen.getAllByTestId('agent-stale-plugin-entry')).toHaveLength(2));
    expect(onChange).toHaveBeenCalledWith({
      tools: ['read_file', 'plugin__demo__hello', 'plugin__demo__other', 'plugin__gone__*'],
    });
    const textarea = document.getElementById('agent-tools') as HTMLTextAreaElement;
    expect(textarea.value).not.toContain('plugin__ghost__run');
    expect(textarea.value).toContain('plugin__demo__other');
  });

  it('hides the section when the lifecycle list fails to load', async () => {
    listPlugins.mockRejectedValue(new Error('backend down'));
    renderForm(makeAgent(['plugin__ghost__run', 'plugin__demo__hello']));

    // 运行快照渲染完成后仍不出现标注区（读不到≠无记录）
    expect(await screen.findByText('demo · hello')).toBeInTheDocument();
    expect(screen.queryByTestId('agent-stale-plugin-entries')).not.toBeInTheDocument();
  });

  it('hides the section when every plugin entry is live or non-plugin', async () => {
    renderForm(makeAgent(['plugin__demo__hello', 'read_file', 'plugin__*']));

    expect(await screen.findByText('demo · hello')).toBeInTheDocument();
    expect(screen.queryByTestId('agent-stale-plugin-entries')).not.toBeInTheDocument();
  });
});
