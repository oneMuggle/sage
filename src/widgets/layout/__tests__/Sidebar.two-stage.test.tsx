import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { I18nProvider } from '../../../shared/lib/i18n';
import { useStore } from '../../../shared/lib/store';
import { Sidebar } from '../Sidebar';

/**
 * UX-IA R3 批次 B：两段式布局（56px 功能 rail + 内容列）。
 *
 * 对标 Codex / Cursor / Claude。左栏此前是一列 15 项的平铺列表（9 个路由链接 +
 * 6 个内容分组），导航与内容没有层级；现在拆成两段物理分离。
 */

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
    updateSettings: vi.fn(),
  }),
}));

vi.mock('../../../features/manage-endpoints/api', () => ({
  testEndpointConnection: vi.fn().mockResolvedValue({ success: true, latency: 12 }),
}));

beforeEach(() => {
  localStorage.clear();
  const setState = useStore.setState as unknown as (partial: Record<string, unknown>) => void;
  setState({ currentSessionId: null, sessions: [] });
});

function renderSidebar(props: Partial<Parameters<typeof Sidebar>[0]> = {}) {
  return render(
    <I18nProvider defaultLocale="zh">
      <MemoryRouter initialEntries={['/chat']}>
        <Sidebar width={300} {...props} />
      </MemoryRouter>
    </I18nProvider>,
  );
}

describe('Sidebar — 两段式布局', () => {
  it('展开态同时渲染 rail 与内容列', () => {
    renderSidebar();
    expect(screen.getByTestId('sidebar-rail')).toBeInTheDocument();
    expect(screen.getByTestId('sidebar-content')).toBeInTheDocument();
  });

  it('折叠态只剩 rail，内容列整段不渲染', () => {
    renderSidebar({ collapsed: true });
    expect(screen.getByTestId('sidebar-rail')).toBeInTheDocument();
    expect(screen.queryByTestId('sidebar-content')).toBeNull();
    expect(screen.queryByTestId('sidebar-primary-actions')).toBeNull();
  });

  it('rail 固定 56px，从总宽里扣（width 仍是总宽，Layout 零改动）', () => {
    const { container } = renderSidebar({ width: 320 });
    const rail = screen.getByTestId('sidebar-rail');
    expect(rail).toHaveStyle({ width: '56px' });
    // 外层 aside 承载总宽 —— Layout 的 wrapper/拖拽手柄仍按这个值算
    const aside = container.querySelector('aside');
    expect(aside).toHaveStyle({ width: '320px' });
  });

  it('导航全部收进 rail，内容列只剩列表', () => {
    renderSidebar();
    // 作用域入口在 rail
    const railNav = screen.getByTestId('sidebar-rail-nav');
    expect(railNav).toContainElement(screen.getByRole('link', { name: '记忆' }));
    expect(railNav).toContainElement(screen.getByRole('link', { name: '技能' }));
    // 内容列表不在 rail 里
    const content = screen.getByTestId('sidebar-content');
    expect(content).toContainElement(screen.getByText('会话'));
    expect(content).toContainElement(screen.getByText('项目'));
    expect(railNav).not.toContainElement(screen.getByText('会话'));
  });

  it('设置入口移入 rail 底部（全页只有一个「设置」链接）', () => {
    renderSidebar();
    const rail = screen.getByTestId('sidebar-rail');
    expect(rail).toContainElement(screen.getByTestId('sidebar-settings-link'));
    expect(screen.getAllByRole('link', { name: '设置' })).toHaveLength(1);
  });

  it('内容列是唯一滚动容器（nav 上只有一个 overflow-y-auto）', () => {
    const { container } = renderSidebar();
    const scrollables = Array.from(container.querySelectorAll('.overflow-y-auto')).filter(
      (el) => !screen.getByTestId('sidebar-rail').contains(el),
    );
    expect(scrollables).toHaveLength(1);
    expect(scrollables[0]).toBe(screen.getByTestId('sidebar-scroll'));
  });

  it('rail 入口带 sr-only 文本标签（图标按钮也可被文本查询命中）', () => {
    renderSidebar();
    expect(screen.getByText('记忆')).toBeInTheDocument();
    expect(screen.getByText('知识库')).toBeInTheDocument();
  });

  it('折叠/展开 toggle 恒在 rail 底部，按状态切换 testid', () => {
    const onToggle = vi.fn();
    const { rerender } = renderSidebar({ onToggleCollapse: onToggle });
    expect(screen.getByTestId('sidebar-collapse-button')).toBeInTheDocument();
    expect(screen.queryByTestId('sidebar-expand-button')).toBeNull();

    rerender(
      <I18nProvider defaultLocale="zh">
        <MemoryRouter initialEntries={['/chat']}>
          <Sidebar width={300} collapsed onToggleCollapse={onToggle} />
        </MemoryRouter>
      </I18nProvider>,
    );
    expect(screen.getByTestId('sidebar-expand-button')).toBeInTheDocument();
    expect(screen.queryByTestId('sidebar-collapse-button')).toBeNull();
  });
});
