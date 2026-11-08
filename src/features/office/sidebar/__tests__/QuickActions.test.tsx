import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { QuickActions, quickCommandsForTab } from '../QuickActions';

vi.mock('../../../../shared/lib/i18n', () => ({
  useI18n: () => ({ t: (key: string) => key, locale: 'zh', setLocale: vi.fn() }),
}));

describe('quickCommandsForTab', () => {
  it('returns the documents command set', () => {
    expect(quickCommandsForTab('documents').map((c) => c.command)).toEqual([
      '/audit',
      '/rules',
      '/summarize',
      '/translate',
    ]);
  });

  it('returns the latex command set', () => {
    expect(quickCommandsForTab('latex').map((c) => c.command)).toEqual([
      '/compile',
      '/citations',
      '/formulas',
    ]);
  });
});

describe('QuickActions', () => {
  it('renders one button per command and forwards clicks', () => {
    const onCommand = vi.fn();
    render(<QuickActions tab="rules" onCommand={onCommand} />);

    const buttons = screen.getAllByRole('button');
    expect(buttons).toHaveLength(3);
    fireEvent.click(buttons[0]);
    expect(onCommand).toHaveBeenCalledWith('/rules');
  });
});
