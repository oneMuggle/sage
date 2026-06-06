/**
 * SkillCard 测试
 * - 渲染 name/description/triggers/usageCount
 * - 切换开关触发 onToggle(name, enabled)
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
        usageCount={42}
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
        usageCount={0}
        onToggle={onToggle}
      />,
    );
    const checkbox = screen.getByRole('checkbox');
    fireEvent.click(checkbox);
    expect(onToggle).toHaveBeenCalledWith('weather', true);
  });
});
