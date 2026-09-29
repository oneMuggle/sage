/**
 * UX-IA R1（2026-09-29，docs/plans/2026-09-29_ux-ia-round1.md）：
 * A1 顶部主操作条（新建对话 / 搜索）· A2 设置移至页脚 · A3 分组默认顺序与折叠。
 */
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { OPEN_COMMAND_PALETTE_EVENT } from '../../../shared/lib/commandPaletteEvents';
import { I18nProvider } from '../../../shared/lib/i18n';
import { useStore } from '../../../shared/lib/store';
import { SIDER_SECTIONS_STORAGE_KEY } from '../../sidebar';
import { Sidebar } from '../Sidebar';

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

function PathProbe() {
  const location = useLocation();
  return <div data-testid="current-path">{location.pathname}</div>;
}

function renderSidebarAt(path: string) {
  return render(
    <I18nProvider defaultLocale="zh">
      <MemoryRouter initialEntries={[path]}>
        <Sidebar />
        <PathProbe />
      </MemoryRouter>
    </I18nProvider>,
  );
}

beforeEach(() => {
  localStorage.clear();
  const setState = useStore.setState as unknown as (partial: Record<string, unknown>) => void;
  setState({ currentSessionId: null, sessions: [] });
});

describe('Sidebar — primary actions (UX-IA R1 A1)', () => {
  it('primary new-chat button navigates to /welcome', () => {
    renderSidebarAt('/chat');
    fireEvent.click(screen.getByTestId('sidebar-new-chat-primary'));
    expect(screen.getByTestId('current-path').textContent).toBe('/welcome');
  });

  it('search button dispatches the open-command-palette event', () => {
    const listener = vi.fn();
    window.addEventListener(OPEN_COMMAND_PALETTE_EVENT, listener);
    try {
      renderSidebarAt('/chat');
      fireEvent.click(screen.getByTestId('sidebar-search-button'));
      expect(listener).toHaveBeenCalledTimes(1);
    } finally {
      window.removeEventListener(OPEN_COMMAND_PALETTE_EVENT, listener);
    }
  });
});

describe('Sidebar — settings moved to footer (UX-IA R1 A2)', () => {
  it('renders settings as a footer link instead of a primary nav row', () => {
    renderSidebarAt('/chat');
    const link = screen.getByTestId('sidebar-settings-link');
    expect(link).toHaveAttribute('href', '/settings');
    expect(screen.getAllByRole('link', { name: '设置' })).toHaveLength(1);
  });

  it('highlights the footer link on the settings route', () => {
    renderSidebarAt('/settings');
    expect(screen.getByTestId('sidebar-settings-link').className).toContain('text-primary');
  });
});

describe('Sidebar — section defaults (UX-IA R1 A3)', () => {
  it('keeps a stored layout untouched for existing users', () => {
    localStorage.setItem(
      SIDER_SECTIONS_STORAGE_KEY,
      JSON.stringify({
        order: ['conversations', 'todos', 'cron', 'git', 'project', 'team'],
        collapsed: [],
      }),
    );
    renderSidebarAt('/chat');
    const stored = JSON.parse(localStorage.getItem(SIDER_SECTIONS_STORAGE_KEY) as string);
    expect(stored.order[0]).toBe('conversations');
    expect(stored.collapsed).toEqual([]);
  });
});
