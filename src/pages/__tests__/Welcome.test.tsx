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
  vi.stubGlobal(
    'ResizeObserver',
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  );
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
  vi.unstubAllGlobals();
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
    expect(screen.getAllByTestId('recommendation-card')).toHaveLength(5);
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

  it('opens a deliverable brief instead of dropping a bare prompt into the input', () => {
    renderWelcome();
    const reportCard = screen.getAllByTestId('recommendation-card')[0]!;
    fireEvent.click(reportCard);
    const goal = screen.getByTestId('task-brief-goal') as HTMLTextAreaElement;
    expect(goal.value).toContain('报告');
    // 未配置对话模型时不承诺可以启动任务
    expect(screen.getByTestId('task-brief-submit')).toBeDisabled();
  });

  it('creates a session when submitting from the input card', async () => {
    renderWelcome();
    const textarea = screen.getByRole('textbox');
    fireEvent.change(textarea, { target: { value: '需要一份报告' } });
    fireEvent.keyDown(textarea, { key: 'Enter', shiftKey: false });

    // Wait for the async createSession promise
    await new Promise((resolve) => setTimeout(resolve, 10));
    expect(createSessionMock).toHaveBeenCalled();
  });

  it('shows toast.error on createSession failure', async () => {
    createSessionMock.mockRejectedValue(new Error('boom'));
    renderWelcome();
    const textarea = screen.getByRole('textbox');
    fireEvent.change(textarea, { target: { value: '需要一份报告' } });
    fireEvent.keyDown(textarea, { key: 'Enter', shiftKey: false });

    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(toastError).toHaveBeenCalled();
  });
});
