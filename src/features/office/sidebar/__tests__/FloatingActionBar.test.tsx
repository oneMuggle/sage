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

    expect(screen.getByTestId('office-floating-action-rewrite')).toBeInTheDocument();
    expect(screen.getByTestId('office-floating-action-chat')).toBeInTheDocument();
    expect(screen.getByTestId('office-floating-action-edit')).toBeInTheDocument();
    expect(screen.getByTestId('office-floating-action-audit')).toBeInTheDocument();

    fireEvent.click(screen.getByTestId('office-floating-action-audit'));
    expect(onAction).toHaveBeenCalledWith('audit');
  });

  it('dismisses on Escape', () => {
    const onDismiss = vi.fn();
    render(
      <FloatingActionBar
        anchorRect={{ top: 100, left: 40, width: 60 }}
        canApply
        onAction={vi.fn()}
        onDismiss={onDismiss}
      />,
    );

    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onDismiss).toHaveBeenCalledTimes(1);
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
