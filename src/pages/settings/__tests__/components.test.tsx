// @vitest-environment jsdom
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { AdvancedSection, ApplyModeBadge, Toggle } from '../components';

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
