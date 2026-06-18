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
});
