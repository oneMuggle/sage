// @vitest-environment jsdom
import { act, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { FEATURE_UNLOCK_STORAGE_KEY } from '../../../shared/lib/hooks/useFeatureUnlock';
import { I18nProvider } from '../../../shared/lib/i18n';
import { useStore } from '../../../shared/lib/store';
import { Sidebar } from '../../../widgets/layout/Sidebar';
import { ArenaAccountsToggle } from '../ArenaAccountsToggle';

vi.mock('../../../features/manage-settings/useSettings', () => ({
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

vi.mock('../../../features/manage-endpoints/api', () => ({
  testEndpointConnection: vi.fn().mockResolvedValue({ success: false }),
}));

beforeEach(() => {
  localStorage.clear();
  const setState = useStore.setState as unknown as (partial: Record<string, unknown>) => void;
  setState({ currentSessionId: null, sessions: [] });
});

/**
 * 把 Sidebar 与 ArenaAccountsToggle 渲染到同一棵 React 树，
 * 通过共享 `FEATURE_UNLOCK_LOCK_EVENT` / `FEATURE_UNLOCK_EVENT` +
 * localStorage 实现真实跨组件联动（避免 mock 内部通信）。
 */
function renderBoth(initialPath = '/chat') {
  return render(
    <I18nProvider defaultLocale="zh">
      <MemoryRouter initialEntries={[initialPath]}>
        <Sidebar />
        <main>
          <ArenaAccountsToggle />
        </main>
      </MemoryRouter>
    </I18nProvider>,
  );
}

describe('ArenaAccountsToggle — unit', () => {
  it('renders off by default and shows the description', () => {
    render(<ArenaAccountsToggle />);
    expect(screen.getByText('Arena 自动化')).toBeInTheDocument();
    expect(screen.getByText(/侧边栏显示「Arena 账号」入口/)).toBeInTheDocument();
    expect(screen.getByTestId('toggle-arena-accounts')).toHaveClass('bg-line-strong');
  });

  it('hydrates the on state from localStorage', () => {
    localStorage.setItem(FEATURE_UNLOCK_STORAGE_KEY, JSON.stringify(['arena-accounts']));
    render(<ArenaAccountsToggle />);
    expect(screen.getByTestId('toggle-arena-accounts')).toHaveClass('bg-primary');
  });

  it('clicking the toggle persists arena-accounts to localStorage', () => {
    render(<ArenaAccountsToggle />);
    const toggle = screen.getByTestId('toggle-arena-accounts');
    fireEvent.click(toggle);
    const stored = JSON.parse(localStorage.getItem(FEATURE_UNLOCK_STORAGE_KEY) as string);
    expect(stored).toContain('arena-accounts');
    expect(toggle).toHaveClass('bg-primary');
  });

  it('clicking twice (on then off) removes the key from localStorage', () => {
    render(<ArenaAccountsToggle />);
    const toggle = screen.getByTestId('toggle-arena-accounts');
    fireEvent.click(toggle); // off → on
    fireEvent.click(toggle); // on → off
    const raw = localStorage.getItem(FEATURE_UNLOCK_STORAGE_KEY);
    const stored = raw == null ? [] : JSON.parse(raw);
    expect(stored).not.toContain('arena-accounts');
    expect(toggle).toHaveClass('bg-line-strong');
  });
});

/**
 * Sidebar ↔ ArenaAccountsToggle 端到端集成测试 (review #5):
 * 不 mock useFeatureUnlock,验证两个组件通过共享 localStorage +
 * 自定义事件真实联动。
 */
describe('ArenaAccountsToggle — Sidebar integration', () => {
  it('turning the toggle off in settings removes the sidebar entry immediately', () => {
    // 前置：先解锁让 Sidebar 显示入口
    localStorage.setItem(FEATURE_UNLOCK_STORAGE_KEY, JSON.stringify(['arena-accounts']));
    renderBoth('/chat');
    expect(screen.getByText('Arena 账号')).toBeInTheDocument();

    // 设置页 toggle off → 侧边栏入口应当立刻消失
    act(() => {
      fireEvent.click(screen.getByTestId('toggle-arena-accounts'));
    });
    expect(screen.queryByText('Arena 账号')).not.toBeInTheDocument();
    const stored = JSON.parse(localStorage.getItem(FEATURE_UNLOCK_STORAGE_KEY) as string);
    expect(stored).not.toContain('arena-accounts');
  });

  it('turning the toggle on in settings makes the sidebar entry appear immediately', () => {
    renderBoth('/chat');
    expect(screen.queryByText('Arena 账号')).not.toBeInTheDocument();

    // 设置页 toggle on → 侧边栏入口出现
    act(() => {
      fireEvent.click(screen.getByTestId('toggle-arena-accounts'));
    });
    expect(screen.getByText('Arena 账号')).toBeInTheDocument();
    const stored = JSON.parse(localStorage.getItem(FEATURE_UNLOCK_STORAGE_KEY) as string);
    expect(stored).toContain('arena-accounts');
  });

  it('visiting /arena-accounts directly hydrates the settings toggle as on', () => {
    // 路由直接访问 → Sidebar 自动 sticky-unlock
    renderBoth('/arena-accounts');
    expect(screen.getByText('Arena 账号')).toBeInTheDocument();

    // 设置页 toggle 应 hydrate 为 ON
    expect(screen.getByTestId('toggle-arena-accounts')).toHaveClass('bg-primary');
  });
});