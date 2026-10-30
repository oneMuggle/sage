/**
 * R17-A1: SkillCard 钉住（pin）交互测试。
 *
 * - onPin 提供时渲染「钉住 / 取消钉住」按钮，点击回传 (name, 期望态)
 * - pinned 徽标随状态切换（📌 已钉住 / 未钉住）
 * - onPin 未提供时不渲染（旧调用方兼容）
 */
import { fireEvent, render as rtlRender, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { I18nProvider } from '../../../shared/lib/i18n';
import SkillCard from '../SkillCard';

function I18nWrapper({ children }: { children: React.ReactNode }) {
  return <I18nProvider defaultLocale="zh">{children}</I18nProvider>;
}

const render = (ui: React.ReactElement, options?: Parameters<typeof rtlRender>[1]) =>
  rtlRender(ui, { wrapper: I18nWrapper, ...options });

const base = {
  name: 'search',
  description: '搜索网络信息并整理结果',
  triggers: ['搜索'],
  enabled: true,
  usage_count: 3,
  onToggle: vi.fn(),
};

describe('SkillCard pin (R17-A1)', () => {
  it('renders pin button and calls onPin(name, true) when unpinned', () => {
    const onPin = vi.fn();
    render(<SkillCard {...base} pinned={false} onPin={onPin} />);

    fireEvent.click(screen.getByRole('button', { name: '钉住 search' }));
    expect(onPin).toHaveBeenCalledWith('search', true);
    expect(screen.getByText('未钉住')).toBeInTheDocument();
  });

  it('renders unpin button and pinned badge when pinned', () => {
    const onPin = vi.fn();
    render(<SkillCard {...base} pinned onPin={onPin} />);

    fireEvent.click(screen.getByRole('button', { name: '取消钉住 search' }));
    expect(onPin).toHaveBeenCalledWith('search', false);
    expect(screen.getByText('📌 已钉住')).toBeInTheDocument();
  });

  it('does not render pin controls when onPin is absent', () => {
    render(<SkillCard {...base} />);

    expect(screen.queryByRole('button', { name: /钉住 search/ })).not.toBeInTheDocument();
  });
});
