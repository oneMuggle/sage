import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { I18nProvider } from '../../../shared/lib/i18n';
import { Sidebar } from '../../layout/Sidebar';

const SECTIONS_CONFIG_KEY = 'sage:sider:sections:v1';

// UX-IA R3 批次 0：左栏分组从 6 个收敛到 3 个（todos/cron 降级为一级导航项，
// team 占位删除）。这些断言按「分组 key 集合」而非标题文案编写——
// 待办/定时任务仍是左栏可见入口，只是形态从分组变成导航项（用文案断言会歧义）。
const EXPECTED_SECTION_KEYS = ['project', 'conversations', 'git'];

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

function sectionKeys(container: HTMLElement): string[] {
  return Array.from(container.querySelectorAll('[data-section-key]')).map(
    (el) => el.getAttribute('data-section-key') ?? '',
  );
}

describe('Sidebar Sections Integration', () => {
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

  it('renders the three remaining sections in default order', () => {
    const { container } = render(
      <I18nProvider>
        <MemoryRouter>
          <Sidebar />
        </MemoryRouter>
      </I18nProvider>,
    );

    expect(sectionKeys(container)).toEqual(EXPECTED_SECTION_KEYS);
    expect(screen.getByText('会话')).toBeInTheDocument();
    expect(screen.getByText('项目')).toBeInTheDocument();
  });

  it('no longer renders the removed todos/cron/team sections', () => {
    const { container } = render(
      <I18nProvider>
        <MemoryRouter>
          <Sidebar />
        </MemoryRouter>
      </I18nProvider>,
    );

    const keys = sectionKeys(container);
    expect(keys).not.toContain('todos');
    expect(keys).not.toContain('cron');
    // team 是占位实现（"Phase 6 才接入"），未接入前不占左栏位置
    expect(keys).not.toContain('team');
    expect(screen.queryByText('团队')).toBeNull();
  });

  it('promotes todos/scheduled to nav entries so no feature is lost', () => {
    render(
      <I18nProvider>
        <MemoryRouter>
          <Sidebar />
        </MemoryRouter>
      </I18nProvider>,
    );

    // 原 TodoSection / CronJobSection 的作用只是"预览 + 跳转整页"，
    // 整页仍在，因此入口从分组迁移到导航项即可（消除同一列里的重复标签）。
    expect(screen.getByRole('link', { name: '待办' })).toHaveAttribute('href', '/todos');
    expect(screen.getByRole('link', { name: '定时任务' })).toHaveAttribute('href', '/scheduled');
  });

  it('updates localStorage when collapsing a section', async () => {
    render(
      <I18nProvider>
        <MemoryRouter>
          <Sidebar />
        </MemoryRouter>
      </I18nProvider>,
    );

    // UX-IA R1 A3: 默认顺序为 项目 → 会话 → …，低频分组默认折叠；
    // 第一个「折叠」按钮属于首个展开分组（项目）
    const collapseButtons = screen.getAllByRole('button', { name: '折叠' });
    fireEvent.click(collapseButtons[0]);

    await waitFor(() => {
      const stored = localStorage.getItem(SECTIONS_CONFIG_KEY);
      expect(stored).toBeTruthy();
      const parsed = JSON.parse(stored!);
      expect(parsed.collapsed).toContain('project');
      expect(parsed.order[0]).toBe('project');
    });
  });

  it('drops removed section keys from stored state', async () => {
    // 老用户 localStorage 里仍留有 todos/cron/team —— reconcile 后应只剩 3 个，
    // 否则 renderSection 会命中 default 分支返回 null 留下空 div。
    localStorage.setItem(
      SECTIONS_CONFIG_KEY,
      JSON.stringify({
        order: ['conversations', 'todos', 'cron', 'project', 'team'],
        collapsed: ['cron', 'todos', 'team'],
      }),
    );

    const { container } = render(
      <I18nProvider>
        <MemoryRouter>
          <Sidebar />
        </MemoryRouter>
      </I18nProvider>,
    );

    await waitFor(() => {
      // 存量顺序里 conversations 排第一，reconcile 保留该顺序并把缺失项追加到末尾；
      // 断言重点是「已删除的 todos/cron/team 不再出现在 order 里」。
      expect(sectionKeys(container)).toEqual(['conversations', 'project', 'git']);
    });
  });

  it('persists collapsed state after re-render', async () => {
    // git 是唯一默认折叠的分组：预置 collapsed:['git']
    localStorage.setItem(
      SECTIONS_CONFIG_KEY,
      JSON.stringify({ order: EXPECTED_SECTION_KEYS, collapsed: ['git'] }),
    );

    render(
      <I18nProvider>
        <MemoryRouter>
          <Sidebar />
        </MemoryRouter>
      </I18nProvider>,
    );

    await waitFor(() => {
      const expandButtons = screen.getAllByRole('button', { name: '展开' });
      expect(expandButtons.length).toBeGreaterThan(0);
    });
  });

  it('persists section order from localStorage', async () => {
    localStorage.setItem(
      SECTIONS_CONFIG_KEY,
      JSON.stringify({ order: ['conversations', 'project', 'git'], collapsed: [] }),
    );

    const { container } = render(
      <I18nProvider>
        <MemoryRouter>
          <Sidebar />
        </MemoryRouter>
      </I18nProvider>,
    );

    await waitFor(() => {
      expect(sectionKeys(container)).toEqual(['conversations', 'project', 'git']);
    });
  });

  it('handles corrupt localStorage gracefully', async () => {
    localStorage.setItem(SECTIONS_CONFIG_KEY, '{invalid json');

    const { container } = render(
      <I18nProvider>
        <MemoryRouter>
          <Sidebar />
        </MemoryRouter>
      </I18nProvider>,
    );

    await waitFor(() => {
      expect(sectionKeys(container)).toEqual(EXPECTED_SECTION_KEYS);
    });
  });

  it('recovers from incomplete section order in localStorage', async () => {
    const incompleteOrder = { order: ['conversations'], collapsed: [] };
    localStorage.setItem(SECTIONS_CONFIG_KEY, JSON.stringify(incompleteOrder));

    const { container } = render(
      <I18nProvider>
        <MemoryRouter>
          <Sidebar />
        </MemoryRouter>
      </I18nProvider>,
    );

    await waitFor(() => {
      // 存量只有 conversations：reconcile 保留它并补齐缺失的 project/git
      expect(sectionKeys(container)).toEqual(['conversations', 'project', 'git']);
    });
  });
});
