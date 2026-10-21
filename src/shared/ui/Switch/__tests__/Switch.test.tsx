import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { Switch } from '../Switch';

describe('Switch', () => {
  it('renders with role=switch and aria-checked=false by default', () => {
    // Arrange + Act
    render(<Switch aria-label="Auto refresh" />);

    // Assert
    const switchEl = screen.getByRole('switch');
    expect(switchEl).toHaveAttribute('aria-checked', 'false');
    expect(switchEl).toBeEnabled();
  });

  it('reflects controlled checked state in aria-checked', () => {
    // Arrange + Act
    render(<Switch aria-label="Auto refresh" checked onCheckedChange={() => {}} />);

    // Assert
    expect(screen.getByRole('switch')).toHaveAttribute('aria-checked', 'true');
  });

  it('calls onCheckedChange with the next state when clicked', () => {
    // Arrange
    const onCheckedChange = vi.fn();
    render(<Switch aria-label="Auto refresh" onCheckedChange={onCheckedChange} />);

    // Act
    fireEvent.click(screen.getByRole('switch'));

    // Assert
    expect(onCheckedChange).toHaveBeenCalledOnce();
    expect(onCheckedChange).toHaveBeenCalledWith(true);
  });

  it('does not toggle when disabled', () => {
    // Arrange
    const onCheckedChange = vi.fn();
    render(<Switch aria-label="Auto refresh" disabled onCheckedChange={onCheckedChange} />);

    // Act
    fireEvent.click(screen.getByRole('switch'));

    // Assert
    expect(onCheckedChange).not.toHaveBeenCalled();
    expect(screen.getByRole('switch')).toHaveAttribute('aria-checked', 'false');
  });

  it('toggles in uncontrolled mode when clicked twice', () => {
    // Arrange
    render(<Switch aria-label="Auto refresh" />);
    const switchEl = screen.getByRole('switch');

    // Act
    fireEvent.click(switchEl);

    // Assert
    expect(switchEl).toHaveAttribute('aria-checked', 'true');

    // Act
    fireEvent.click(switchEl);

    // Assert
    expect(switchEl).toHaveAttribute('aria-checked', 'false');
  });

  it('formats switch state summary and JSON (Phase P119)', async () => {
    const { formatSwitchStateSummary, formatSwitchStateJson } = await import('../Switch');
    expect(formatSwitchStateSummary({ label: 'Auto refresh', checked: true, disabled: false })).toBe(
      'Auto refresh · checked · disabled=false',
    );
    expect(
      JSON.parse(formatSwitchStateJson({ label: 'Auto refresh', checked: true, disabled: false })),
    ).toEqual({
      label: 'Auto refresh',
      checked: true,
      disabled: false,
    });
  });
});
