/**
 * Chat 页 配置缺失警告条 测试
 *
 * 覆盖 Chat.tsx 中：
 *   - hasConfig 派生（active endpoint.baseUrl && modelSelections.chatModelId）
 *   - data-testid="config-warning" 警告条
 *   - 跳转设置链接 (useNavigate → '/settings')
 *   - ChatInput 的 disabled 透传
 *
 * 不发起任何真实 IPC/localStorage;useSettings 与 useNavigate 都被 mock。
 */
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

// 必须使用工厂函数，vitest 才能正确 hoist
const navigateMock = vi.fn();
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return {
    ...actual,
    useNavigate: () => navigateMock,
  };
});

const useSettingsMock = vi.fn();
vi.mock('../../features/manage-settings/useSettings', () => ({
  useSettings: () => useSettingsMock(),
}));

vi.mock('../../shared/api/desktopInvoke', () => ({
  invoke: vi.fn().mockRejectedValue(new Error('should not reach IPC')),
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

import { useStore } from '../../shared/lib/store';
import { Chat } from '../Chat';

describe('Chat — config warning banner', () => {
  beforeEach(() => {
    navigateMock.mockReset();
    // 没有 active endpoint，没有 chatModelId → hasConfig = false
    useSettingsMock.mockReturnValue({
      settings: {
        endpoints: [],
        modelSelections: { chatModelId: null, visionModelId: null, embeddingModelId: null },
        maxContext: 4096,
        temperature: 0.7,
      },
      updateSettings: vi.fn(),
      resetSettings: vi.fn(),
    });
    useStore.setState({ messages: [], currentSessionId: null, sessions: [] });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('renders the warning banner, the settings link and disables ChatInput', () => {
    render(
      <MemoryRouter>
        <Chat />
      </MemoryRouter>,
    );

    // 警告条 data-testid
    expect(screen.getByTestId('config-warning')).toBeInTheDocument();

    // 前往设置 链接存在
    expect(screen.getByText(/前往设置/)).toBeInTheDocument();

    // ChatInput 的 textarea 处于 disabled 状态 (Chat.tsx 把 disabled 透传)
    const textarea = screen.getByPlaceholderText(/输入消息/);
    expect(textarea).toBeDisabled();

    // 点击 "前往设置" 触发 navigate('/settings')
    fireEvent.click(screen.getByText(/前往设置/));
    expect(navigateMock).toHaveBeenCalledWith('/settings');
  });

  it('hides the warning banner and enables ChatInput when config is present', () => {
    useSettingsMock.mockReturnValue({
      settings: {
        endpoints: [
          {
            id: 'ep-1',
            name: 'Test',
            baseUrl: 'https://api.example.test/v1',
            apiKey: 'sk-test',
            isActive: true,
            discoveredModels: [],
            lastDiscoveredAt: null,
          },
        ],
        modelSelections: { chatModelId: 'gpt-test', visionModelId: null, embeddingModelId: null },
        maxContext: 4096,
        temperature: 0.7,
      },
      updateSettings: vi.fn(),
      resetSettings: vi.fn(),
    });

    render(
      <MemoryRouter>
        <Chat />
      </MemoryRouter>,
    );

    expect(screen.queryByTestId('config-warning')).not.toBeInTheDocument();
    expect(screen.queryByText(/前往设置/)).not.toBeInTheDocument();

    const textarea = screen.getByPlaceholderText(/输入消息/);
    expect(textarea).not.toBeDisabled();
  });
});
