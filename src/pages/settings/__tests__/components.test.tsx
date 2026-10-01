// @vitest-environment jsdom
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { AdvancedSection, ApplyModeBadge, SettingRow, Toggle } from '../components';

describe('settings shared components', () => {
  it('renders the Chinese apply-mode label', () => {
    render(<ApplyModeBadge mode="next-run" />);
    expect(screen.getByText('保存后：下次 Run')).toBeInTheDocument();
  });

  it('keeps advanced content collapsed by default', () => {
    render(
      <AdvancedSection title="高级设置">
        <div>advanced controls</div>
      </AdvancedSection>,
    );

    expect(screen.getByText('advanced controls')).not.toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: /高级设置/ }));
    expect(screen.getByText('advanced controls')).toBeVisible();
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
    const { container } = render(
      <SettingRow label="流式输出" anchor="streaming">
        <Toggle value onChange={() => {}} />
      </SettingRow>,
    );
    expect(container.querySelector('[data-settings-anchor="streaming"]')).not.toBeNull();
  });

  it('omits the attribute when no anchor is registered', () => {
    // 未登记锚点的行必须完全不受影响 —— 定位逻辑找不到时静默降级为「只切 tab」。
    const { container } = render(
      <SettingRow label="未登记项">
        <Toggle value onChange={() => {}} />
      </SettingRow>,
    );
    expect(container.querySelector('[data-settings-anchor]')).toBeNull();
  });
});
