import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { CommandInput } from '../CommandInput';

vi.mock('../../../../shared/lib/i18n', () => ({
  useI18n: () => ({ t: (key: string) => key, locale: 'zh', setLocale: vi.fn() }),
}));

describe('CommandInput', () => {
  it('submits on Enter and clears the field', () => {
    const onSubmit = vi.fn();
    render(<CommandInput disabled={false} pending={false} onSubmit={onSubmit} />);

    const textarea = screen.getByTestId('office-ai-command-input');
    fireEvent.change(textarea, { target: { value: '/audit' } });
    fireEvent.keyDown(textarea, { key: 'Enter' });

    expect(onSubmit).toHaveBeenCalledWith('/audit');
    expect((textarea as HTMLTextAreaElement).value).toBe('');
  });

  it('inserts a newline on Shift+Enter without submitting', () => {
    const onSubmit = vi.fn();
    render(<CommandInput disabled={false} pending={false} onSubmit={onSubmit} />);

    const textarea = screen.getByTestId('office-ai-command-input');
    fireEvent.change(textarea, { target: { value: 'a' } });
    fireEvent.keyDown(textarea, { key: 'Enter', shiftKey: true });

    expect(onSubmit).not.toHaveBeenCalled();
  });

  it('does not submit blank input', () => {
    const onSubmit = vi.fn();
    render(<CommandInput disabled={false} pending={false} onSubmit={onSubmit} />);

    fireEvent.keyDown(screen.getByTestId('office-ai-command-input'), { key: 'Enter' });

    expect(onSubmit).not.toHaveBeenCalled();
  });
});
