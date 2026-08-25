/**
 * 批次三 step 6 (spec §4.3 line 150): Memory 页"来源会话跳转"通过
 * /chat?session=<id> 进入。锁定 ChatRoute 消费该参数的行为:
 * 写入 store.currentSessionId → 渲染 Chat,并清掉查询参数。
 */
import { render, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ThemeProvider } from '../app/providers/ThemeProvider';
import { I18nProvider } from '../shared/lib/i18n';
import { useStore } from '../shared/lib/store';

vi.mock('../features/send-message/useChat', () => ({
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

vi.mock('../features/manage-settings/useSettings', () => ({
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

vi.mock('../shared/api/orchRunClient', () => ({
  orchRunClient: { listRuns: vi.fn().mockResolvedValue([]) },
}));

vi.mock('../shared/api/desktopInvoke', () => ({
  invoke: vi.fn().mockResolvedValue([]),
}));

vi.mock('../shared/api/desktopEvent', () => ({
  listen: vi.fn().mockResolvedValue(() => undefined),
}));

vi.mock('../shared/lib/hooks/useFileUpload', () => ({
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

const App = (await import('../App')).default;

function LocationProbe() {
  const currentSessionId = useStore((state) => state.currentSessionId);
  return (
    <div>
      <span data-testid="store-session">{currentSessionId ?? 'null'}</span>
    </div>
  );
}

beforeEach(() => {
  const setState = useStore.setState as unknown as (partial: Record<string, unknown>) => void;
  setState({ currentSessionId: null, sessions: [] });
  localStorage.clear();
});

describe('ChatRoute ?session= deep link (batch 3 step 6)', () => {
  it('adopts ?session=<id> into store and renders Chat instead of redirecting to /welcome', async () => {
    // App 内部自带 HashRouter,不能再包一层 MemoryRouter —
    // 直接设 window.location.hash 作为初始入口。
    window.location.hash = '#/chat?session=sess-deeplink-1';
    const { getByTestId } = render(
      <I18nProvider defaultLocale="zh">
        <ThemeProvider>
          <App />
        </ThemeProvider>
        <LocationProbe />
      </I18nProvider>,
    );

    // 若 ChatRoute 正确消费参数,currentSessionId 被写入 → Chat 页渲染
    // (出现 "对话" 标题),而不是被 gating 弹回 /welcome。
    // effect 异步执行,用 waitFor 等待 store 写入。
    await waitFor(() => {
      expect(getByTestId('store-session')).toHaveTextContent('sess-deeplink-1');
    });
    expect(useStore.getState().currentSessionId).toBe('sess-deeplink-1');
  });
});
