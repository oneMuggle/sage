import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { FloatingActionBar } from '../FloatingActionBar';

vi.mock('../../../../shared/lib/i18n', () => ({
  useI18n: () => ({ t: (key: string) => key, locale: 'zh', setLocale: vi.fn() }),
}));

describe('FloatingActionBar', () => {
  it('renders nothing without an anchor rect', () => {
    const { container } = render(
      <FloatingActionBar anchorRect={null} canApply onAction={vi.fn()} onDismiss={vi.fn()} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it('renders four capabilities and fires the chosen one', () => {
    const onAction = vi.fn();
    render(
      <FloatingActionBar
        anchorRect={{ top: 100, left: 40, width: 60 }}
        canApply
        onAction={onAction}
        onDismiss={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByTestId('office-floating-action-audit'));
    expect(onAction).toHaveBeenCalledWith('audit');
  });

  it('disables apply-dependent actions when canApply is false', () => {
    render(
      <FloatingActionBar
        anchorRect={{ top: 100, left: 40, width: 60 }}
        canApply={false}
        onAction={vi.fn()}
        onDismiss={vi.fn()}
      />,
    );
    expect(screen.getByTestId('office-floating-action-edit')).toBeDisabled();
  });
});
