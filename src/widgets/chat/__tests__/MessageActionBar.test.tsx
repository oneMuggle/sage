// @vitest-environment jsdom
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { I18nProvider } from '../../../shared/lib/i18n';
import { MessageActionBar } from '../MessageActionBar';

describe('MessageActionBar progressive disclosure', () => {
  const baseMessage = {
    id: 'msg-1',
    session_id: 'sess-1',
    role: 'assistant' as const,
    content: 'Hello from assistant',
    created_at: Date.now(),
  };

  it('groups primary actions separately from secondary actions and toggles overflow state', () => {
    const onFork = vi.fn();
    const onRewind = vi.fn();
    const onDelete = vi.fn();
    const onRegenerate = vi.fn();
    const onQuote = vi.fn();
    const onSaveToMemory = vi.fn();

    render(
      <I18nProvider>
        <MessageActionBar
          message={baseMessage}
        onFork={onFork}
        onRewind={onRewind}
        onDelete={onDelete}
        onRegenerate={onRegenerate}
        onQuote={onQuote}
        onSaveToMemory={onSaveToMemory}
        />
      </I18nProvider>,
    );

    const primary = screen.getByTestId('message-primary-actions');
    const secondary = screen.getByTestId('message-secondary-actions');
    const toggle = screen.getByTestId('message-more-actions-toggle');

    expect(primary.querySelector('[data-testid="copy-message"]')).not.toBeNull();
    expect(primary.querySelector('[data-testid="regenerate-message"]')).not.toBeNull();
    expect(primary.querySelector('[data-testid="quote-message"]')).not.toBeNull();

    expect(secondary.querySelector('[data-testid="fork-message"]')).not.toBeNull();
    expect(secondary.querySelector('[data-testid="rewind-message"]')).not.toBeNull();
    expect(secondary.querySelector('[data-testid="save-to-memory"]')).not.toBeNull();
    expect(secondary.querySelector('[data-testid="delete-message"]')).not.toBeNull();

    expect(toggle.getAttribute('aria-expanded')).toBe('false');
    expect(secondary.className).toContain('hidden');

    fireEvent.click(toggle);
    expect(toggle.getAttribute('aria-expanded')).toBe('true');
    expect(secondary.className).not.toContain('hidden');

    fireEvent.click(screen.getByTestId('fork-message'));
    expect(onFork).toHaveBeenCalledWith('msg-1');
  });
});
