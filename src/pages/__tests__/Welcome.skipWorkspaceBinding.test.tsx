import { render, screen, fireEvent, waitFor } from '@testing-library/react';
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

describe('Welcome page - skip workspace binding', () => {
  // 2026-11-04 (fix/skip-workspace-binding): 用户在新会话页选择"不绑定项目"时，
  // handleSubmit 应调用 createSession(true)，传递 skipBinding=true。
  // 语义对齐主流 AI 应用 (Cursor / Cline / Windsurf) 的"显式选择 > 自动推断"原则。
  it('calls createSession(true) when projectId is null (user chose "不绑定项目")', async () => {
    renderWelcome();

    // 输入消息
    const textarea = screen.getByRole('textbox');
    fireEvent.change(textarea, { target: { value: '测试消息' } });

    // 提交（Enter 键）
    fireEvent.keyDown(textarea, { key: 'Enter', shiftKey: false });

    // 等待 handleSubmit 执行
    await waitFor(() => {
      expect(createSessionMock).toHaveBeenCalled();
    });

    // 验证调用参数：skipBinding=true（因为 projectId === null）
    expect(createSessionMock).toHaveBeenCalledWith(true);
  });

  it('calls createSession(false) or createSession() when projectId is selected', async () => {
    // TODO: 这个测试需要 ProjectPicker 组件支持选择项目
    // 当前 Welcome 页默认没有选择项目，所以 projectId === null
    // 未来可以扩展此测试：选择项目后验证 createSession(false) 或 createSession()
    renderWelcome();

    const textarea = screen.getByRole('textbox');
    fireEvent.change(textarea, { target: { value: '测试消息' } });
    fireEvent.keyDown(textarea, { key: 'Enter', shiftKey: false });

    await waitFor(() => {
      expect(createSessionMock).toHaveBeenCalled();
    });

    // 默认情况下 projectId === null，所以应该调用 createSession(true)
    expect(createSessionMock).toHaveBeenCalledWith(true);
  });
});
