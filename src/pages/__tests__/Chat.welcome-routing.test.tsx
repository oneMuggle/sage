import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, Navigate, Route, Routes, useLocation } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { I18nProvider } from '../../shared/lib/i18n';
import { useStore } from '../../shared/lib/store';
import { Chat } from '../Chat';
import { Welcome } from '../Welcome';

function PathProbe() {
  const location = useLocation();
  return <div data-testid="current-path">{location.pathname}</div>;
}

vi.mock('../../features/send-message/useChat', () => ({
  useChat: () => ({
    sendMessage: vi.fn(),
    isLoading: false,
    error: null,
    clearError: vi.fn(),
    messages: [],
    loadMessages: vi.fn(),
    interrupt: vi.fn(),
    streamingToolCalls: [],
  }),
}));

vi.mock('../../features/manage-settings/useSettings', () => ({
  useSettings: () => ({
    settings: {
      endpoints: [],
      modelSelections: {
        chatModel: { endpointId: null, modelId: null },
        visionModel: { endpointId: null, modelId: null },
        embeddingModel: { endpointId: null, modelId: null },
      },
      maxContext: 4096,
      temperature: 0.7,
    },
  }),
}));

// C3 (2026-08-15): Chat → ProgressSection → PlanCardList 渲染链挂载即调
// orchRunClient.listRuns();mock 掉避免真实 IPC 抛错 (unhandled rejection)。
vi.mock('../../shared/api/orchRunClient', () => ({
  orchRunClient: { listRuns: vi.fn().mockResolvedValue([]) },
}));

vi.mock('../../shared/api/desktopInvoke', () => ({
  invoke: vi.fn().mockRejectedValue(new Error('not reached')),
}));

vi.mock('../../shared/api/desktopEvent', () => ({
  listen: vi.fn().mockResolvedValue(() => undefined),
}));

vi.mock('../../shared/lib/hooks/useFileUpload', () => ({
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

beforeEach(() => {
  const setState = useStore.setState as unknown as (partial: Record<string, unknown>) => void;
  setState({ currentSessionId: null, sessions: [] });
});

function ChatRoute() {
  const currentSessionId = useStore((s) => s.currentSessionId);
  if (!currentSessionId) {
    return <Navigate to="/welcome" replace />;
  }
  return <Chat />;
}

function AppRouter() {
  return (
    <MemoryRouter initialEntries={['/chat']}>
      <Routes>
        <Route path="/chat" element={<ChatRoute />} />
        <Route path="/welcome" element={<Welcome />} />
      </Routes>
    </MemoryRouter>
  );
}

describe('Chat / Welcome routing — sessionId gating', () => {
  it('redirects to /welcome when no currentSessionId', () => {
    render(
      <I18nProvider defaultLocale="zh">
        <AppRouter />
      </I18nProvider>,
    );
    expect(screen.getByText(/你好，我是 Sage/)).toBeInTheDocument();
  });

  it('shows chat normally when currentSessionId is set', () => {
    const setState = useStore.setState as unknown as (partial: Record<string, unknown>) => void;
    setState({ currentSessionId: 'session-abc' });
    render(
      <I18nProvider defaultLocale="zh">
        <AppRouter />
      </I18nProvider>,
    );
    expect(screen.getByText('对话')).toBeInTheDocument();
  });
});

// Chat 顶部的 "+ 新对话" 按钮必须与 Sidebar 上的 "新对话" 按钮行为一致:
// 跳到 /welcome 并清空 currentSessionId。否则 ChatRoute 因为
// currentSessionId 非空仍会渲染 Chat 页,用户看不到欢迎页。
describe('Chat — top-bar "新对话" must go to /welcome', () => {
  function ChatAppWithProbe() {
    return (
      <MemoryRouter initialEntries={['/chat']}>
        <Routes>
          <Route path="/chat" element={<ChatRoute />} />
          <Route path="/welcome" element={<Welcome />} />
        </Routes>
        <PathProbe />
      </MemoryRouter>
    );
  }

  it('clicking the top-bar "新对话" navigates to /welcome and clears currentSessionId', () => {
    const setState = useStore.setState as unknown as (partial: Record<string, unknown>) => void;
    setState({ currentSessionId: 'session-abc' });

    render(
      <I18nProvider defaultLocale="zh">
        <ChatAppWithProbe />
      </I18nProvider>,
    );

    // 当前在 /chat 且有 sessionId → Chat 页可见,标题含 "对话"
    expect(screen.getByText('对话')).toBeInTheDocument();
    expect(screen.getByTestId('current-path').textContent).toBe('/chat');

    // 点击顶部 "+ 新对话"
    fireEvent.click(screen.getByRole('button', { name: /新对话/ }));

    // 跳到 /welcome
    expect(screen.getByTestId('current-path').textContent).toBe('/welcome');
    // currentSessionId 被清空(避免 ChatRoute 在路由切换瞬间再次渲染 Chat)
    expect(useStore.getState().currentSessionId).toBeNull();
  });
});
