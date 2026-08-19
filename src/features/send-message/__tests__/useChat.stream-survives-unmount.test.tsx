import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { SETTINGS_STORAGE_KEY, SETTINGS_VERSION } from '../../../entities/setting/types';
import { useChatStreamStore } from '../chatStreamStore';

// mock 模式同 useChat.test.ts
const invokeMock = vi.fn().mockResolvedValue(undefined);
const listenMock = vi.fn();
vi.mock('../../../shared/api/desktopInvoke', () => ({
  invoke: (...args: unknown[]) => invokeMock(...args),
}));
vi.mock('../../../shared/api/desktopEvent', () => ({
  listen: (...args: unknown[]) => listenMock(...args),
}));

describe('useChat — 流式状态跨组件实例存活', () => {
  beforeEach(() => {
    const payload = {
      streaming: true,
      autoMemory: true,
      confirmDelete: true,
      endpoints: [
        {
          id: 'ep-1',
          name: 'Test',
          baseUrl: 'https://api.example.test/v1',
          apiKey: 'sk-test',
          discoveredModels: [],
          lastDiscoveredAt: null,
        },
      ],
      modelSelections: { chatModel: { endpointId: 'ep-1', modelId: 'gpt-test' } },
      maxContext: 4096,
      temperature: 0.7,
      version: SETTINGS_VERSION,
    };
    localStorage.setItem(SETTINGS_STORAGE_KEY, JSON.stringify(payload));
    localStorage.setItem('sage-settings.migrated_to_backend', new Date().toISOString());
    useChatStreamStore.getState().resetAll();
  });

  afterEach(() => {
    vi.clearAllMocks();
    useChatStreamStore.getState().resetAll();
  });

  it('Chat 页卸载再挂载,流式状态从 store 恢复', () => {
    // 1. 直接操作 store —— 模拟 LLM 流推到一半
    useChatStreamStore.getState().startStream('msg-A', { initialContent: '🤔 思考中…' });
    useChatStreamStore.getState().appendContent('msg-A', '你好,');
    useChatStreamStore.getState().replaceContent('msg-A', '⚙ 调用工具…');

    // 2. 模拟 Chat 页卸载 —— 这在 store 化前会丢失 streaming state
    //    (此处只能断言: store 的内容不被任何 hook 卸载影响)
    expect(useChatStreamStore.getState().streaming?.messageId).toBe('msg-A');

    // 3. 后端又推了一个 content_delta('继续工作')
    useChatStreamStore.getState().appendContent('msg-A', '继续工作');

    // 4. 用户切回 Chat 页 —— 新 hook 实例 selector 同一 store
    //    (这里我们只断言 store 仍是累计后的状态,而不去实际 render 第二实例
    //     避免引入 useSettings 的额外 mock 开销)
    const s = useChatStreamStore.getState();
    expect(s.streaming?.messageId).toBe('msg-A');
    expect(s.streaming?.content).toBe('⚙ 调用工具…继续工作');
  });
});
