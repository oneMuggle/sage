import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { I18nProvider } from '../../../shared/lib/i18n';
import { CronExpressionPicker } from '../CronExpressionPicker';

function renderPicker(props: React.ComponentProps<typeof CronExpressionPicker>) {
  return render(
    <I18nProvider>
      <CronExpressionPicker {...props} />
    </I18nProvider>,
  );
}

describe('CronExpressionPicker', () => {
  it('renders preset chips and a custom input', () => {
    renderPicker({ value: '', onChange: () => {} });
    expect(screen.getAllByTestId(/^cron-preset-/).length).toBeGreaterThan(0);
    expect(screen.getByTestId('cron-input')).toBeTruthy();
  });

  it('clicking a preset calls onChange with the preset cron', () => {
    const onChange = vi.fn();
    renderPicker({ value: '', onChange });
    fireEvent.click(screen.getByTestId('cron-preset-hourly'));
    expect(onChange).toHaveBeenCalledWith('0 * * * *');
  });

  it('typing in custom input calls onChange with the new value', () => {
    const onChange = vi.fn();
    renderPicker({ value: '', onChange });
    const input = screen.getByTestId('cron-input') as HTMLInputElement;
    fireEvent.change(input, { target: { value: '0 8 * * *' } });
    expect(onChange).toHaveBeenCalledWith('0 8 * * *');
  });

  it('shows inline error when custom cron is invalid', () => {
    renderPicker({ value: 'garbage', onChange: () => {} });
    expect(screen.getByTestId('cron-error')).toBeTruthy();
  });

  it('does not show error when value is a valid cron', () => {
    renderPicker({ value: '0 8 * * *', onChange: () => {} });
    expect(screen.queryByTestId('cron-error')).toBeNull();
  });
});
