import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { TodoQuickAdd } from '../TodoQuickAdd';

describe('TodoQuickAdd', () => {
  it('previews parsed due date, priority and tags', () => {
    render(<TodoQuickAdd isOpen onClose={() => {}} onSubmit={vi.fn()} />);

    fireEvent.change(screen.getByTestId('quick-add-input'), {
      target: { value: '明天下午3点 交报告 !高 #工作' },
    });

    const preview = screen.getByTestId('quick-add-preview');
    expect(preview.textContent).toContain('优先级 高');
    expect(preview.textContent).toContain('工作');
  });

  it('submits the parsed input and closes', async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    const onClose = vi.fn();
    render(<TodoQuickAdd isOpen onClose={onClose} onSubmit={onSubmit} />);

    fireEvent.change(screen.getByTestId('quick-add-input'), {
      target: { value: '后天 9点半 开会' },
    });
    fireEvent.click(screen.getByTestId('quick-add-submit'));

    await waitFor(() => {
      expect(onSubmit).toHaveBeenCalledWith(
        expect.objectContaining({
          title: '开会',
          due_at: expect.stringMatching(/T09:30:00$/),
        }),
      );
    });
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });

  it('disables submit when the input is empty', () => {
    render(<TodoQuickAdd isOpen onClose={() => {}} onSubmit={vi.fn()} />);
    expect(screen.getByTestId('quick-add-submit')).toBeDisabled();
  });
});
