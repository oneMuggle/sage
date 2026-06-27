import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { I18nProvider } from '../../shared/lib/i18n';
import { useStore } from '../../shared/lib/store';
import { Welcome } from '../Welcome';

const toastError = vi.fn();
vi.mock('sonner', () => ({
  toast: {
    error: (...args: unknown[]) => toastError(...args),
    info: vi.fn(),
    success: vi.fn(),
  },
}));

const createSessionMock = vi.fn();
const setCurrentSessionIdMock = vi.fn();

beforeEach(() => {
  toastError.mockReset();
  createSessionMock.mockReset();
  createSessionMock.mockResolvedValue('new-session-id');
  setCurrentSessionIdMock.mockReset();
  // Partial store state for testing; cast through unknown to satisfy eslint no-explicit-any
  const setState = useStore.setState as unknown as (partial: Record<string, unknown>) => void;
  setState({
    currentSessionId: null,
    sessions: [],
    createSession: createSessionMock,
    setCurrentSessionId: setCurrentSessionIdMock,
    loadSessions: vi.fn(),
    loadMessages: vi.fn(),
  });
});

afterEach(() => {
  const setState = useStore.setState as unknown as (partial: Record<string, unknown>) => void;
  setState({ currentSessionId: null, sessions: [] });
});

function renderWelcome() {
  return render(
    <I18nProvider defaultLocale="zh">
      <MemoryRouter>
        <Welcome />
      </MemoryRouter>
    </I18nProvider>,
  );
}

describe('Welcome page', () => {
  it('renders hero, input card, recommendations and quick action bar', () => {
    renderWelcome();
    expect(screen.getByText(/你好，我是 Sage/)).toBeInTheDocument();
    expect(screen.getByTestId('welcome-input-card')).toBeInTheDocument();
    expect(screen.getAllByTestId('recommendation-card')).toHaveLength(3);
    expect(screen.getByRole('toolbar', { name: /quick actions/ })).toBeInTheDocument();
  });

  it('auto-focuses the input card on mount', () => {
    renderWelcome();
    expect(screen.getByRole('textbox')).toHaveFocus();
  });

  it('shows a placeholder on the textarea', () => {
    renderWelcome();
    const textarea = screen.getByRole('textbox');
    expect(textarea).toHaveAttribute('placeholder');
    expect(textarea.getAttribute('placeholder')?.length).toBeGreaterThan(0);
  });

  it('clicking a recommendation card prefills the input', () => {
    renderWelcome();
    const codeCard = screen.getAllByTestId('recommendation-card')[0]!;
    fireEvent.click(codeCard);
    const textarea = screen.getByRole('textbox') as HTMLTextAreaElement;
    expect(textarea.value.startsWith('帮我写代码')).toBe(true);
  });

  it('creates a session when submitting prefilled prompt', async () => {
    renderWelcome();
    const codeCard = screen.getAllByTestId('recommendation-card')[0]!;
    fireEvent.click(codeCard);

    const textarea = screen.getByRole('textbox');
    fireEvent.keyDown(textarea, { key: 'Enter', shiftKey: false });

    // Wait for the async createSession promise
    await new Promise((resolve) => setTimeout(resolve, 10));
    expect(createSessionMock).toHaveBeenCalled();
  });

  it('shows toast.error on createSession failure', async () => {
    createSessionMock.mockRejectedValue(new Error('boom'));
    renderWelcome();
    const codeCard = screen.getAllByTestId('recommendation-card')[0]!;
    fireEvent.click(codeCard);
    const textarea = screen.getByRole('textbox');
    fireEvent.keyDown(textarea, { key: 'Enter', shiftKey: false });

    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(toastError).toHaveBeenCalled();
  });
});
