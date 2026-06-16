import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

// 必须使用工厂函数，vitest 才能正确 hoist
vi.mock('../../../shared/api/desktopInvoke', () => ({
  invoke: vi.fn().mockRejectedValue(new Error('should not reach IPC')),
}));

vi.mock('../../../shared/api/desktopEvent', () => ({
  listen: vi.fn().mockResolvedValue(() => undefined),
}));

vi.mock('../manage-settings/useSettings', () => ({
  useSettings: () => ({
    settings: {
      endpoints: [], // 无 active 端点
      modelSelections: { chatModelId: null, visionModelId: null, embeddingModelId: null },
      maxContext: 4096,
      temperature: 0.7,
    },
    updateSettings: vi.fn(),
    resetSettings: vi.fn(),
  }),
}));

import { useStore } from '../../../shared/lib/store';
import { useChat } from '../useChat';

describe('useChat — input should never be swallowed on validation failure', () => {
  beforeEach(() => {
    useStore.setState({ messages: [], currentSessionId: 'sid-1' });
  });

  it('appends the user message to the store even when no endpoint is configured', async () => {
    const { result } = renderHook(() => useChat());

    await act(async () => {
      await result.current.sendMessage('hello world');
    });

    const messages = useStore.getState().messages;
    const userMsg = messages.find((m) => m.role === 'user');
    expect(userMsg).toBeDefined();
    expect(userMsg?.content).toBe('hello world');
    expect(result.current.error).toMatch(/未配置|未选择/);
  });
});
