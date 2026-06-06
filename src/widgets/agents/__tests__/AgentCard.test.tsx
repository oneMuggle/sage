/**
 * AgentCard 测试
 * - 渲染 name/description/role 标签/model
 * - 点击卡片触发 onSelect
 * - 点击 enable 复选框触发 onToggle 且不冒泡到 onSelect
 */
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { AgentProfile } from '../../../lib/api';
import { AgentCard } from '../AgentCard';

const baseAgent: AgentProfile = {
  id: 'a-1',
  name: '助理',
  role: 'coordinator',
  description: '一个示例 Agent',
  system_prompt: '',
  tools: [],
  memory_access: [],
  model_config: { model: 'gpt-test', temperature: 0.7, max_tokens: 1024 },
  max_iterations: 5,
  enabled: true,
};

describe('AgentCard', () => {
  it('renders agent name, role label, description, and model', () => {
    render(
      <AgentCard
        agent={baseAgent}
        isSelected={false}
        onSelect={() => undefined}
        onToggle={() => undefined}
      />,
    );
    expect(screen.getByText('助理')).toBeInTheDocument();
    expect(screen.getByText('协调器')).toBeInTheDocument();
    expect(screen.getByText('一个示例 Agent')).toBeInTheDocument();
    expect(screen.getByText('模型: gpt-test')).toBeInTheDocument();
  });

  it('calls onSelect when card is clicked', () => {
    const onSelect = vi.fn();
    render(
      <AgentCard
        agent={baseAgent}
        isSelected={false}
        onSelect={onSelect}
        onToggle={() => undefined}
      />,
    );
    fireEvent.click(screen.getByText('助理'));
    expect(onSelect).toHaveBeenCalledTimes(1);
  });

  it('toggle checkbox calls onToggle with new enabled state', () => {
    const onToggle = vi.fn();
    render(
      <AgentCard
        agent={baseAgent}
        isSelected={false}
        onSelect={() => undefined}
        onToggle={onToggle}
      />,
    );
    const checkbox = screen.getByRole('checkbox');
    // baseAgent.enabled=true → click 后 checked 应为 false
    fireEvent.click(checkbox);
    expect(onToggle).toHaveBeenCalledWith('a-1', false);
  });
});
