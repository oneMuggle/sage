/**
 * Recap (2026-11-08): /recap slash command tests
 *
 * Selecting /recap calls the `onRecap` callback (provided by the Chat page),
 * which invokes sessionApi.recap and renders the RecapCard. ChatInput itself
 * does not call the API directly — same contract as /compact 与 /learn。
 */
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { I18nProvider } from '../../../shared/lib/i18n';
import { ChatInput } from '../ChatInput';
import { slashCommands } from '../slashCommands';

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

function openSlashMenuAndSelectRecap() {
  const input = screen.getByPlaceholderText(/输入消息/);
  fireEvent.change(input, { target: { value: '/recap' } });
  // SlashCommandMenu items fire onSelect via onMouseDown
  const menuItem = screen.getByRole('button', { name: /\/recap/ });
  fireEvent.mouseDown(menuItem);
  return input;
}

describe('/recap slash command — static definition', () => {
  it('is registered in slashCommands with mode "recap"', () => {
    const recap = slashCommands.find((c) => c.name === 'recap');
    expect(recap).toBeDefined();
    expect(recap!.mode).toBe('recap');
  });

  it('has a description explaining its purpose', () => {
    const recap = slashCommands.find((c) => c.name === 'recap');
    expect(recap).toBeDefined();
    expect(recap!.description.length).toBeGreaterThan(0);
  });
});

describe('ChatInput — /recap action', () => {
  it('shows /recap in the slash command menu when typing /', () => {
    renderWithI18n(<ChatInput onSend={vi.fn()} />);

    const input = screen.getByPlaceholderText(/输入消息/);
    fireEvent.change(input, { target: { value: '/' } });

    expect(screen.getByRole('button', { name: /\/recap/ })).toBeInTheDocument();
  });

  it('invokes onRecap (not onSend) when /recap is selected', () => {
    const onSend = vi.fn();
    const onRecap = vi.fn();
    renderWithI18n(<ChatInput onSend={onSend} onRecap={onRecap} />);

    const input = openSlashMenuAndSelectRecap();

    expect(onRecap).toHaveBeenCalledTimes(1);
    expect(onSend).not.toHaveBeenCalled();
    expect((input as HTMLTextAreaElement).value).toBe('');
  });

  it('is a safe no-op when onRecap is not provided', () => {
    const onSend = vi.fn();
    renderWithI18n(<ChatInput onSend={onSend} />);

    const input = openSlashMenuAndSelectRecap();

    expect(onSend).not.toHaveBeenCalled();
    expect((input as HTMLTextAreaElement).value).toBe('');
  });

  it('ignores /recap while loading (onRecap NOT called)', () => {
    const onSend = vi.fn();
    const onRecap = vi.fn();
    renderWithI18n(<ChatInput onSend={onSend} onRecap={onRecap} isLoading />);

    openSlashMenuAndSelectRecap();

    expect(onRecap).not.toHaveBeenCalled();
    expect(onSend).not.toHaveBeenCalled();
  });

  it('ignores /recap while disabled (onRecap NOT called)', () => {
    const onSend = vi.fn();
    const onRecap = vi.fn();
    renderWithI18n(<ChatInput onSend={onSend} onRecap={onRecap} disabled />);

    openSlashMenuAndSelectRecap();

    expect(onRecap).not.toHaveBeenCalled();
    expect(onSend).not.toHaveBeenCalled();
  });
});
