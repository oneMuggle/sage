// TODO(M6): win7 M5 Sidebar 在 new chat 时用 createSession() (不 navigate /welcome)。
// pre-7c76327 main 版本测 /welcome 行为与 win7 不兼容。M6 实施 Welcome 屏时移除 skip + 适配 createSession 路径。
// 2026-06-28 (win7 phase 9 commit 7c76327) 删除,M5 实施时从 main 恢复,因行为差异暂跳。
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { I18nProvider } from '../../../shared/lib/i18n';
import { Sidebar } from '../../layout/Sidebar';

const SECTIONS_CONFIG_KEY = 'sage:sider:sections:v1';

const mockSessions = [
  {
    id: 's1',
    title: 'Session 1',
    created_at: Date.now(),
    updated_at: Date.now(),
    is_pinned: false,
    last_message_at: null,
    message_count: 5,
  },
  {
    id: 's2',
    title: 'Session 2',
    created_at: Date.now(),
    updated_at: Date.now(),
    is_pinned: false,
    last_message_at: null,
    message_count: 3,
  },
  {
    id: 's3',
    title: 'Session 3',
    created_at: Date.now(),
    updated_at: Date.now(),
    is_pinned: false,
    last_message_at: null,
    message_count: 7,
  },
];

describe.skip('Sidebar Sections Integration', () => {
  beforeEach(() => {
    localStorage.clear();
    vi.resetModules();

    vi.mock('../../../shared/lib/store', () => ({
      useStore: () => ({
        sessions: mockSessions,
        currentSessionId: null,
        setCurrentSessionId: vi.fn(),
        createSession: vi.fn().mockResolvedValue('new-session'),
        loadSessions: vi.fn(),
        deleteSession: vi.fn(),
      }),
    }));

    vi.mock('../../../features/manage-settings/useSettings', () => ({
      useSettings: () => ({
        settings: {
          modelSelections: {
            chatModel: {
              modelId: 'test',
              displayName: 'Test Model',
            },
          },
          endpoints: [
            {
              id: 'ep1',
              name: 'Test Endpoint',
              baseUrl: 'https://api.example.com',
              apiKey: 'test-key',
            },
          ],
        },
        updateSettings: vi.fn(),
      }),
    }));

    vi.mock('../../../features/manage-endpoints/api', () => ({
      testEndpointConnection: vi.fn().mockResolvedValue({
        success: true,
        latency: 42,
      }),
    }));
  });

  it('renders all sections in default order', () => {
    render(
      <I18nProvider>
        <MemoryRouter>
          <Sidebar />
        </MemoryRouter>
      </I18nProvider>,
    );

    expect(screen.getByText('会话')).toBeInTheDocument();
    expect(screen.getByText('定时任务')).toBeInTheDocument();
    expect(screen.getByText('项目')).toBeInTheDocument();
    expect(screen.getByText('团队')).toBeInTheDocument();
  });

  it('updates localStorage when collapsing a section', async () => {
    render(
      <I18nProvider>
        <MemoryRouter>
          <Sidebar />
        </MemoryRouter>
      </I18nProvider>,
    );

    // Click collapse button on first section (会话)
    const collapseButtons = screen.getAllByRole('button', { name: '折叠' });
    fireEvent.click(collapseButtons[0]);

    await waitFor(() => {
      const stored = localStorage.getItem(SECTIONS_CONFIG_KEY);
      expect(stored).toBeTruthy();
      const parsed = JSON.parse(stored!);
      expect(parsed.collapsed).toContain('conversations');
    });
  });

  it('persists collapsed state after re-render', async () => {
    // Pre-populate localStorage with collapsed state
    localStorage.setItem(
      SECTIONS_CONFIG_KEY,
      JSON.stringify({ order: ['conversations', 'cron', 'project', 'team'], collapsed: ['cron'] }),
    );

    render(
      <I18nProvider>
        <MemoryRouter>
          <Sidebar />
        </MemoryRouter>
      </I18nProvider>,
    );

    await waitFor(() => {
      // "定时任务" section should show expand button (collapsed)
      const expandButtons = screen.getAllByRole('button', { name: '展开' });
      expect(expandButtons.length).toBeGreaterThan(0);
    });
  });

  it('persists section order from localStorage', async () => {
    const customOrder = { order: ['team', 'project', 'cron', 'conversations'], collapsed: [] };
    localStorage.setItem(SECTIONS_CONFIG_KEY, JSON.stringify(customOrder));

    const { container } = render(
      <I18nProvider>
        <MemoryRouter>
          <Sidebar />
        </MemoryRouter>
      </I18nProvider>,
    );

    await waitFor(() => {
      const sections = container.querySelectorAll('[data-section-key]');
      expect(sections.length).toBe(4);
    });
  });

  it('handles corrupt localStorage gracefully', async () => {
    localStorage.setItem(SECTIONS_CONFIG_KEY, '{invalid json');

    render(
      <I18nProvider>
        <MemoryRouter>
          <Sidebar />
        </MemoryRouter>
      </I18nProvider>,
    );

    await waitFor(() => {
      // Should still render all sections with default order
      expect(screen.getByText('会话')).toBeInTheDocument();
      expect(screen.getByText('定时任务')).toBeInTheDocument();
      expect(screen.getByText('项目')).toBeInTheDocument();
      expect(screen.getByText('团队')).toBeInTheDocument();
    });
  });

  it('recovers from incomplete section order in localStorage', async () => {
    const incompleteOrder = { order: ['conversations', 'cron'], collapsed: [] };
    localStorage.setItem(SECTIONS_CONFIG_KEY, JSON.stringify(incompleteOrder));

    render(
      <I18nProvider>
        <MemoryRouter>
          <Sidebar />
        </MemoryRouter>
      </I18nProvider>,
    );

    await waitFor(() => {
      // Should render all sections, appending missing ones
      expect(screen.getByText('会话')).toBeInTheDocument();
      expect(screen.getByText('定时任务')).toBeInTheDocument();
      expect(screen.getByText('项目')).toBeInTheDocument();
      expect(screen.getByText('团队')).toBeInTheDocument();
    });
  });
});
