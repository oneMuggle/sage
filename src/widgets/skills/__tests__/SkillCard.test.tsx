/**
 * SkillCard 测试
 * - 渲染 name/description/triggers/usage_count
 * - 切换开关触发 onToggle(name, enabled)
 * - SKILL.md 适配层 (PR-8): source badge / body 折叠区 / version badge / base_dir
 */
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import SkillCard from '../SkillCard';

describe('SkillCard', () => {
  it('renders skill metadata correctly', () => {
    render(
      <SkillCard
        name="search"
        description="网络搜索能力"
        triggers={['查', '搜索']}
        enabled
        usage_count={42}
        onToggle={() => undefined}
      />,
    );
    expect(screen.getByText('search')).toBeInTheDocument();
    expect(screen.getByText('网络搜索能力')).toBeInTheDocument();
    expect(screen.getByText('查')).toBeInTheDocument();
    expect(screen.getByText('搜索')).toBeInTheDocument();
    expect(screen.getByText('已使用 42 次')).toBeInTheDocument();
  });

  it('toggles enabled state via the switch', () => {
    const onToggle = vi.fn();
    render(
      <SkillCard
        name="weather"
        description="天气查询"
        triggers={['天气']}
        enabled={false}
        usage_count={0}
        onToggle={onToggle}
      />,
    );
    const checkbox = screen.getByRole('checkbox');
    fireEvent.click(checkbox);
    expect(onToggle).toHaveBeenCalledWith('weather', true);
  });

  it('默认 source=builtin, 不显示折叠 body 区', () => {
    render(
      <SkillCard
        name="search"
        description="网络搜索能力"
        triggers={['搜索']}
        enabled
        usage_count={0}
        onToggle={() => undefined}
      />,
    );
    expect(screen.getByText('builtin')).toBeInTheDocument();
    expect(screen.queryByText('查看提示词模板')).not.toBeInTheDocument();
  });

  it('source=skillmd 时显示 skillmd badge + 折叠 body', () => {
    render(
      <SkillCard
        name="code-review"
        description="Review a code diff"
        triggers={['review']}
        enabled
        usage_count={0}
        onToggle={() => undefined}
        source="skillmd"
        body="You are a careful reviewer. Look for bugs."
        version="0.2.0"
        base_dir="/home/user/.sage/skills/code-review"
      />,
    );
    // skillmd badge 显示
    expect(screen.getByText('skillmd')).toBeInTheDocument();
    // version badge
    expect(screen.getByText('v0.2.0')).toBeInTheDocument();
    // 折叠区存在 (默认未展开)
    expect(screen.getByText('查看提示词模板')).toBeInTheDocument();
    // base_dir 在 details 内显示
    expect(screen.getByText(/路径:.*code-review/)).toBeInTheDocument();
  });

  it('source=skillmd 但 body 为空时不显示折叠区', () => {
    render(
      <SkillCard
        name="code-review"
        description="Review a code diff"
        triggers={['review']}
        enabled
        usage_count={0}
        onToggle={() => undefined}
        source="skillmd"
        body=""
      />,
    );
    expect(screen.getByText('skillmd')).toBeInTheDocument();
    expect(screen.queryByText('查看提示词模板')).not.toBeInTheDocument();
  });

  // ===== M9: DispatchMode 元数据渲染 =====

  it('无 dispatch 时不显示 slash command badge', () => {
    render(
      <SkillCard
        name="search"
        description="x"
        triggers={['x']}
        enabled
        usage_count={0}
        onToggle={() => undefined}
      />,
    );
    // 不应有 /search 形式的命令 badge
    expect(screen.queryByText('/search')).not.toBeInTheDocument();
    // 也不应有命令调度 chip
    expect(screen.queryByText(/^tool$/)).not.toBeInTheDocument();
  });

  it('user_invocable=true + user_invocable_name 存在时显示 slash command badge', () => {
    render(
      <SkillCard
        name="code-review"
        description="Review"
        triggers={['review']}
        enabled
        usage_count={0}
        onToggle={() => undefined}
        source="skillmd"
        dispatch={{
          disable_model_invocation: false,
          user_invocable: true,
          user_invocable_name: '/review',
          command_dispatch: 'auto',
        }}
      />,
    );
    // slash command badge 显示
    expect(screen.getByText('/review')).toBeInTheDocument();
  });

  it('user_invocable=true 但 user_invocable_name 为 null 时不显示 slash badge', () => {
    render(
      <SkillCard
        name="code-review"
        description="Review"
        triggers={['review']}
        enabled
        usage_count={0}
        onToggle={() => undefined}
        source="skillmd"
        dispatch={{
          disable_model_invocation: false,
          user_invocable: true,
          user_invocable_name: null,
          command_dispatch: 'auto',
        }}
      />,
    );
    // 无 slash command 时不渲染
    expect(screen.queryByText('/code-review')).not.toBeInTheDocument();
    expect(screen.queryByText('/review')).not.toBeInTheDocument();
  });

  it('command_dispatch=tool 时显示 tool chip', () => {
    render(
      <SkillCard
        name="code-review"
        description="Review"
        triggers={['review']}
        enabled
        usage_count={0}
        onToggle={() => undefined}
        source="skillmd"
        dispatch={{
          disable_model_invocation: false,
          user_invocable: false,
          user_invocable_name: null,
          command_dispatch: 'tool',
        }}
      />,
    );
    // command_dispatch chip 显示
    expect(screen.getByText('tool')).toBeInTheDocument();
  });

  it('command_dispatch=auto (默认) 时不显示额外 chip', () => {
    render(
      <SkillCard
        name="code-review"
        description="Review"
        triggers={['review']}
        enabled
        usage_count={0}
        onToggle={() => undefined}
        source="skillmd"
        dispatch={{
          disable_model_invocation: false,
          user_invocable: false,
          user_invocable_name: null,
          command_dispatch: 'auto',
        }}
      />,
    );
    // auto 模式不渲染特殊 chip (避免 UI 噪音)
    expect(screen.queryByText('auto')).not.toBeInTheDocument();
  });
});
