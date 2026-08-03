/**
 * Task 12: /learn slash command tests
 *
 * The /learn command lets users explicitly trigger a Background Review of
 * the current conversation. Selecting /learn from the slash menu calls the
 * `onLearn` callback (provided by the Chat page), which is responsible for
 * invoking the learnApi and navigating to the Pending Drafts tab.
 *
 * Follows the same pattern as the /compact action tests
 * (ChatInput.compact.test.tsx): onLearn is a callback prop, mirroring
 * onCompact/onClear — ChatInput itself does not call the API directly.
 */
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { I18nProvider } from '../../../shared/lib/i18n';
import { slashCommands } from '../slashCommands';
import { ChatInput } from '../ChatInput';

vi.mock('../../../shared/lib/hooks/useFileUpload', () => ({
  useFileUpload: () => ({
    files: [],
    images: [],
    addFile: vi.fn(),
    addImage: vi.fn(),
    removeFile: vi.fn(),
    removeImage: vi.fn(),
    clearAll: vi.fn(),
    handleDrop: vi.fn(),
    handleDragOver: vi.fn(),
    isDragOver: false,
  }),
}));

const renderWithI18n = (ui: React.ReactElement) =>
  render(<I18nProvider defaultLocale="zh">{ui}</I18nProvider>);

function openSlashMenuAndSelectLearn() {
  const input = screen.getByPlaceholderText(/输入消息/);
  fireEvent.change(input, { target: { value: '/learn' } });
  // SlashCommandMenu items fire onSelect via onMouseDown
  const menuItem = screen.getByRole('button', { name: /\/learn/ });
  fireEvent.mouseDown(menuItem);
  return input;
}

describe('/learn slash command — static definition', () => {
  it('is registered in slashCommands with mode "learn"', () => {
    const learn = slashCommands.find((c) => c.name === 'learn');
    expect(learn).toBeDefined();
    expect(learn!.mode).toBe('learn');
  });

  it('has a description explaining its purpose', () => {
    const learn = slashCommands.find((c) => c.name === 'learn');
    expect(learn).toBeDefined();
    expect(learn!.description.length).toBeGreaterThan(0);
  });
});

describe('ChatInput — /learn action', () => {
  it('shows /learn in the slash command menu when typing /', () => {
    renderWithI18n(<ChatInput onSend={vi.fn()} />);

    const input = screen.getByPlaceholderText(/输入消息/);
    fireEvent.change(input, { target: { value: '/' } });

    expect(screen.getByRole('button', { name: /\/learn/ })).toBeInTheDocument();
  });

  it('invokes onLearn (not onSend) when /learn is selected', () => {
    const onSend = vi.fn();
    const onLearn = vi.fn();
    renderWithI18n(<ChatInput onSend={onSend} onLearn={onLearn} />);

    const input = openSlashMenuAndSelectLearn();

    expect(onLearn).toHaveBeenCalledTimes(1);
    expect(onSend).not.toHaveBeenCalled();
    // Command text is cleared after selection
    expect((input as HTMLTextAreaElement).value).toBe('');
  });

  it('is a safe no-op when onLearn is not provided', () => {
    const onSend = vi.fn();
    renderWithI18n(<ChatInput onSend={onSend} />);

    const input = openSlashMenuAndSelectLearn();

    expect(onSend).not.toHaveBeenCalled();
    expect((input as HTMLTextAreaElement).value).toBe('');
  });

  it('ignores /learn while loading (onLearn NOT called)', () => {
    const onSend = vi.fn();
    const onLearn = vi.fn();
    renderWithI18n(<ChatInput onSend={onSend} onLearn={onLearn} isLoading />);

    openSlashMenuAndSelectLearn();

    expect(onLearn).not.toHaveBeenCalled();
    expect(onSend).not.toHaveBeenCalled();
  });

  it('ignores /learn while disabled (onLearn NOT called)', () => {
    const onSend = vi.fn();
    const onLearn = vi.fn();
    renderWithI18n(<ChatInput onSend={onSend} onLearn={onLearn} disabled />);

    openSlashMenuAndSelectLearn();

    expect(onLearn).not.toHaveBeenCalled();
    expect(onSend).not.toHaveBeenCalled();
  });
});
