/**
 * SkillList 测试 (PR-7) — 验证数据流:
 * - 渲染传入的 skills 数组 (data flow from api → page → widget)
 * - 切换某 skill 开关调 onToggle(name, enabled)
 * - 空数组显示 "暂无技能" 占位
 */
import { fireEvent, render as rtlRender, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { Skill } from '../../../shared/api';
import { I18nProvider } from '../../../shared/lib/i18n';
import SkillList, { formatSkillListJson, formatSkillListMarkdown } from '../SkillList';

function I18nWrapper({ children }: { children: React.ReactNode }) {
  return <I18nProvider defaultLocale="zh">{children}</I18nProvider>;
}

const render = (ui: React.ReactElement, options?: Parameters<typeof rtlRender>[1]) =>
  rtlRender(ui, { wrapper: I18nWrapper, ...options });

const SAMPLE_SKILLS: Skill[] = [
  {
    name: 'search',
    description: '搜索网络信息并整理结果',
    triggers: ['搜索', '查一下'],
    parameters: {},
    examples: [],
    enabled: true,
    usage_count: 12,
  },
  {
    name: 'writer',
    description: '帮助撰写文章',
    triggers: ['写'],
    parameters: {},
    examples: [],
    enabled: false,
    usage_count: 0,
  },
];

describe('SkillList (PR-7)', () => {
  it('renders all skills with name/description/triggers/usage_count', () => {
    render(<SkillList skills={SAMPLE_SKILLS} onToggle={() => undefined} />);

    // 2 个 skill 名称都渲染
    expect(screen.getByText('search')).toBeInTheDocument();
    expect(screen.getByText('writer')).toBeInTheDocument();
    // description
    expect(screen.getByText('搜索网络信息并整理结果')).toBeInTheDocument();
    expect(screen.getByText('帮助撰写文章')).toBeInTheDocument();
    // triggers
    expect(screen.getByText('搜索')).toBeInTheDocument();
    expect(screen.getByText('查一下')).toBeInTheDocument();
    expect(screen.getByText('写')).toBeInTheDocument();
    // usage_count
    expect(screen.getByText('已使用 12 次')).toBeInTheDocument();
    expect(screen.getByText('已使用 0 次')).toBeInTheDocument();
  });

  it('calls onToggle with (name, newEnabled) when switch clicked', () => {
    const onToggle = vi.fn();
    render(<SkillList skills={SAMPLE_SKILLS} onToggle={onToggle} />);

    // 第一个 skill (search) 开关点击 → onToggle('search', false) (因为已 enabled → unchecked)
    const checkboxes = screen.getAllByRole('checkbox');
    expect(checkboxes).toHaveLength(2);
    fireEvent.click(checkboxes[0]); // search 当前 enabled=true, 点击后变 false
    expect(onToggle).toHaveBeenCalledWith('search', false);

    // 第二个 skill (writer) 开关点击 → onToggle('writer', true)
    fireEvent.click(checkboxes[1]);
    expect(onToggle).toHaveBeenCalledWith('writer', true);
  });

  it('shows empty placeholder when no skills', () => {
    render(<SkillList skills={[]} onToggle={() => undefined} />);
    expect(screen.getByText('暂无技能')).toBeInTheDocument();
  });

  it('preserves enabled state from props in checkbox', () => {
    render(<SkillList skills={SAMPLE_SKILLS} onToggle={() => undefined} />);
    const [searchCb, writerCb] = screen.getAllByRole('checkbox');
    // search.enabled=true → checked; writer.enabled=false → unchecked
    expect(searchCb).toBeChecked();
    expect(writerCb).not.toBeChecked();
  });

  it('exports skill list as Markdown and JSON', () => {
    expect(formatSkillListMarkdown([])).toContain('_暂无技能_');
    const md = formatSkillListMarkdown(SAMPLE_SKILLS);
    expect(md).toContain('# 技能列表摘要 (Skill List)');
    expect(md).toContain('- **search** (已启用, 使用 12 次)');
    expect(md).toContain('- **writer** (已禁用, 使用 0 次)');
    const parsed = JSON.parse(formatSkillListJson(SAMPLE_SKILLS));
    expect(parsed.total).toBe(2);

    render(<SkillList skills={SAMPLE_SKILLS} onToggle={() => undefined} />);
  });
});
