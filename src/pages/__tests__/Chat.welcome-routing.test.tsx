import { render, screen } from '@testing-library/react';
import { MemoryRouter, Navigate, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { I18nProvider } from '../../shared/lib/i18n';
import { useStore } from '../../shared/lib/store';
import { Chat } from '../Chat';
import { Welcome } from '../Welcome';

vi.mock('../../features/send-message/useChat', () => ({
  useChat: () => ({
    sendMessage: vi.fn(),
    isLoading: false,
    error: null,
    clearError: vi.fn(),
    messages: [],
    loadMessages: vi.fn(),
    interrupt: vi.fn(),
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
    expect(screen.getByText(/你好，我是 Claude/)).toBeInTheDocument();
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
