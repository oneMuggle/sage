/**
 * R29 契约: 自动路由哨兵绝不落进会话覆盖。
 *
 * 单测只覆盖了 ModelPicker 组件层（onChange 收到 'auto'），但没有证明整条链路:
 * 选「自动路由」→ 提交 → 不应调用 sessionApi.setModelOverride。这条如果坏掉，
 * 用户会以为在用智能路由，实际却被钉死在一个叫 "auto" 的假模型上。
 */
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { DEFAULT_ENDPOINT, DEFAULT_SETTINGS } from '../../entities/setting/types';
import { useSettingsStore } from '../../features/manage-settings/settingsStore';
import { I18nProvider } from '../../shared/lib/i18n';
import { useStore } from '../../shared/lib/store';
import { Welcome } from '../Welcome';

const setModelOverrideMock = vi.fn();
const createSessionMock = vi.fn();
const setCurrentSessionIdMock = vi.fn();

vi.mock('sonner', () => ({
  toast: { error: vi.fn(), info: vi.fn(), success: vi.fn(), warning: vi.fn() },
}));

vi.mock('../../shared/api/sessionApi', () => ({
  sessionApi: {
    setModelOverride: (...args: unknown[]) => setModelOverrideMock(...args),
    list: vi.fn(async () => []),
    create: vi.fn(),
  },
}));

vi.mock('../../entities/model-catalog/api', async () => {
  const actual = await vi.importActual<typeof import('../../entities/model-catalog/api')>(
    '../../entities/model-catalog/api',
  );
  return {
    ...actual,
    listModels: vi.fn(async () => ({ items: [], total: 0, limit: 50, offset: 0 })),
  };
});

const AUTO_LABEL = '自动路由（按任务选择模型）';

function seedAutoRoutingSettings(): void {
  useSettingsStore.setState({
    settings: {
      ...DEFAULT_SETTINGS,
      routing: { mode: 'auto' },
      endpoints: [
        {
          ...DEFAULT_ENDPOINT,
          id: 'ep-1',
          name: 'Ep',
          baseUrl: 'http://127.0.0.1:1234/v1',
          discoveredModels: [{ id: 'gpt-4o', capabilities: ['chat'], endpointId: 'ep-1' }],
          lastDiscoveredAt: 0,
        },
      ],
    },
    isLoading: false,
  });
}

async function renderWelcome(): Promise<void> {
  // 挂载后 Welcome 会异步拉项目/分支/catalog，用 async act 让这些 promise 落进测试体。
  // 打字机占位符的计时器仍会产生既有的 act 警告（与 Welcome.test.tsx 基线一致）。
  await act(async () => {
    render(
      <I18nProvider defaultLocale="zh">
        <MemoryRouter>
          <Welcome />
        </MemoryRouter>
      </I18nProvider>,
    );
  });
}

beforeEach(() => {
  window.localStorage.clear();
  vi.stubGlobal(
    'ResizeObserver',
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  );
  setModelOverrideMock.mockReset();
  createSessionMock.mockReset();
  createSessionMock.mockResolvedValue('new-session-id');
  setCurrentSessionIdMock.mockReset();
  const setState = useStore.setState as unknown as (partial: Record<string, unknown>) => void;
  setState({
    currentSessionId: null,
    sessions: [],
    createSession: createSessionMock,
    setCurrentSessionId: setCurrentSessionIdMock,
    loadSessions: vi.fn(),
    loadMessages: vi.fn(),
  });
  seedAutoRoutingSettings();
});

afterEach(() => {
  vi.unstubAllGlobals();
  window.localStorage.clear();
  const setState = useStore.setState as unknown as (partial: Record<string, unknown>) => void;
  setState({ currentSessionId: null, sessions: [] });
});

describe('Welcome — 自动路由哨兵 (R29)', () => {
  it('选择自动路由后提交, 不写会话模型覆盖且不落 localStorage', async () => {
    await renderWelcome();

    fireEvent.click(screen.getByRole('combobox', { name: '选择模型' }));
    fireEvent.click(screen.getByText(AUTO_LABEL));

    const textarea = screen.getByRole('textbox');
    fireEvent.change(textarea, { target: { value: '写一份周报' } });
    fireEvent.keyDown(textarea, { key: 'Enter', shiftKey: false });

    await waitFor(() => expect(createSessionMock).toHaveBeenCalled());
    await waitFor(() => expect(setCurrentSessionIdMock).toHaveBeenCalled());
    expect(setModelOverrideMock).not.toHaveBeenCalled();
    expect(window.localStorage.getItem('sage-welcome-model')).toBeNull();
  });

  it('旧的 localStorage 里的 auto 读回时归一为「跟随全局」', async () => {
    window.localStorage.setItem('sage-welcome-model', 'auto');
    await renderWelcome();

    // Welcome 挂载后会异步拉项目/分支；用 waitFor 收尾，避免更新落在 act 之外。
    await waitFor(() => expect(screen.getByText(/跟随全局/)).toBeInTheDocument());
    expect(screen.queryByText(AUTO_LABEL)).toBeNull();
  });
});
