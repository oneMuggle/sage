// @vitest-environment jsdom
import { fireEvent, render, screen } from '@testing-library/react';
import type { ReactElement } from 'react';
import { describe, expect, it, vi } from 'vitest';

import { I18nProvider } from '../../../shared/lib/i18n';
import {
  AdvancedSection,
  ApplyModeBadge,
  SettingRow,
  SettingsPageHeader,
  SettingsSection,
  Toggle,
  formatSettingRowAuditJson,
  formatSettingRowAuditSnapshot,
} from '../components';

// SettingRow / ApplyModeBadge / AdvancedSection 都会读 i18n，统一包一层 provider。
function renderZh(ui: ReactElement) {
  return render(<I18nProvider defaultLocale="zh">{ui}</I18nProvider>);
}

describe('settings shared components', () => {
  it('renders the Chinese apply-mode label', () => {
    renderZh(<ApplyModeBadge mode="next-run" />);
    expect(screen.getByText('保存后：下次 Run')).toBeInTheDocument();
  });

  it('renders the English apply-mode label without Chinese residue', () => {
    render(
      <I18nProvider defaultLocale="en">
        <ApplyModeBadge mode="next-run" />
      </I18nProvider>,
    );
    expect(screen.getByText('After save: Next Run')).toBeInTheDocument();
  });

  it('keeps advanced content collapsed by default', () => {
    renderZh(
      <AdvancedSection title="高级设置">
        <div>advanced controls</div>
      </AdvancedSection>,
    );

    const trigger = screen.getByRole('button', { name: /高级设置/ });
    expect(trigger).toHaveAttribute('aria-expanded', 'false');
    expect(screen.getByText('展开')).toBeInTheDocument();
    expect(screen.getByText('advanced controls')).not.toBeVisible();
    fireEvent.click(trigger);
    expect(screen.getByText('advanced controls')).toBeVisible();
    expect(screen.getByText('收起')).toBeInTheDocument();
  });

  it('localizes the expand/collapse hint in English', () => {
    render(
      <I18nProvider defaultLocale="en">
        <AdvancedSection title="Advanced">
          <div>advanced controls</div>
        </AdvancedSection>
      </I18nProvider>,
    );
    expect(screen.getByText('Expand')).toBeInTheDocument();
  });
});

describe('Toggle a11y', () => {
  it('has role="switch" and aria-checked reflecting value', () => {
    render(<Toggle value={true} onChange={() => {}} />);
    const toggle = screen.getByRole('switch');
    expect(toggle).toHaveAttribute('aria-checked', 'true');
  });

  it('aria-checked updates with value prop', () => {
    const { rerender } = render(<Toggle value={false} onChange={() => {}} />);
    const toggle = screen.getByRole('switch');
    expect(toggle).toHaveAttribute('aria-checked', 'false');

    rerender(<Toggle value={true} onChange={() => {}} />);
    expect(toggle).toHaveAttribute('aria-checked', 'true');
  });

  it('calls onChange with toggled value when clicked', () => {
    const onChange = vi.fn();
    render(<Toggle value={false} onChange={onChange} />);
    fireEvent.click(screen.getByRole('switch'));
    expect(onChange).toHaveBeenCalledWith(true);
  });

  it('is disabled when disabled prop is true', () => {
    const onChange = vi.fn();
    render(<Toggle value={false} onChange={onChange} disabled />);
    const toggle = screen.getByRole('switch');
    expect(toggle).toBeDisabled();
    fireEvent.click(toggle);
    expect(onChange).not.toHaveBeenCalled();
  });
});

describe('SettingRow 搜索锚点 (P1-4)', () => {
  it('exposes data-settings-anchor matching the search index key', () => {
    const { container } = renderZh(
      <SettingRow label="流式输出" anchor="streaming">
        <Toggle value onChange={() => {}} />
      </SettingRow>,
    );
    expect(container.querySelector('[data-settings-anchor="streaming"]')).not.toBeNull();
  });

  it('omits the attribute when no anchor is registered', () => {
    // 未登记锚点的行必须完全不受影响 —— 定位逻辑找不到时静默降级为「只切 tab」。
    const { container } = renderZh(
      <SettingRow label="未登记项">
        <Toggle value onChange={() => {}} />
      </SettingRow>,
    );
    expect(container.querySelector('[data-settings-anchor]')).toBeNull();
  });

  it('formats SettingRow audit snapshot/JSON (P103) without hidden copy controls', () => {
    expect(
      formatSettingRowAuditSnapshot({
        label: '流式输出',
        hasDesc: true,
        anchor: 'streaming',
      }),
    ).toBe('label=流式输出|desc=1|anchor=streaming');
    expect(
      JSON.parse(
        formatSettingRowAuditJson({
          label: '未登记项',
          hasDesc: false,
          anchor: null,
        }),
      ),
    ).toEqual({
      label: '未登记项',
      hasDesc: false,
      anchor: null,
    });

    // 2026-10-28：SettingRow 不再渲染 sr-only 的可聚焦审计按钮（键盘/读屏噪音）。
    renderZh(
      <SettingRow label="流式输出" desc="开启流式" anchor="streaming">
        <Toggle value onChange={() => {}} />
      </SettingRow>,
    );
    expect(screen.queryByTestId('setting-row-audit-copy')).not.toBeInTheDocument();
    expect(screen.queryByTestId('setting-row-audit-copy-json')).not.toBeInTheDocument();
  });
});

describe('Settings 标题层级 (2026-11-01)', () => {
  it('页面级 h1 与分组 h2 使用不同层级', () => {
    renderZh(
      <div>
        <SettingsPageHeader title="编排" description="管理编排设置" />
        <SettingsSection title="并发与迭代">
          <div>内容</div>
        </SettingsSection>
      </div>,
    );

    const h1 = screen.getByRole('heading', { level: 1 });
    const h2 = screen.getByRole('heading', { level: 2 });
    expect(h1.textContent).toBe('编排');
    expect(h2.textContent).toBe('并发与迭代');
    expect(screen.getByText('管理编排设置')).toBeInTheDocument();
  });
});
