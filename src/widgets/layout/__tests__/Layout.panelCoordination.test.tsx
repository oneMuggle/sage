// 左右面板联动（UI 优化 2026-10-14 Phase 3）：
// 右栏打开 + 「右栏打开时自动折叠左栏」开启 → 左栏折叠到 56px rail；
// 右栏关闭时不自动恢复；右栏最大化时始终折叠（不受设置影响）。
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../Sidebar', () => ({
  Sidebar: ({ collapsed }: { collapsed: boolean }) => (
    <div data-testid="sidebar-stub" data-collapsed={String(collapsed)} />
  ),
}));
vi.mock('../Titlebar', () => ({ Titlebar: () => null }));
vi.mock('../../system/EndpointStatusBanner', () => ({ EndpointStatusBanner: () => null }));
vi.mock('../../task-center/TaskCenterWidget', () => ({ TaskCenterWidget: () => null }));
vi.mock('../../task-center/DeliveryDrawerHost', () => ({ DeliveryDrawerHost: () => null }));

import { useRightPanelStore } from '../../../features/right-panel/rightPanelStore';
import { Layout } from '../Layout';

function renderLayout() {
  return render(
    <MemoryRouter initialEntries={['/chat']}>
      <Routes>
        <Route path="/chat" element={<Layout />} />
      </Routes>
    </MemoryRouter>,
  );
}

function sidebarCollapsed() {
  return screen.getByTestId('sidebar-stub').getAttribute('data-collapsed') === 'true';
}

describe('Layout — 左右面板联动', () => {
  beforeEach(() => {
    localStorage.clear();
    useRightPanelStore.setState({ open: false, maximized: false });
  });

  it('默认（设置关闭）时右栏打开不折叠左栏', () => {
    useRightPanelStore.getState().setOpen(true);
    renderLayout();
    expect(sidebarCollapsed()).toBe(false);
  });

  it('设置开启时右栏打开自动折叠左栏', () => {
    localStorage.setItem('right-panel-auto-collapse-sidebar', '1');
    useRightPanelStore.getState().setOpen(true);
    renderLayout();
    expect(sidebarCollapsed()).toBe(true);
  });

  it('设置开启 + 右栏关闭时不自动恢复左栏', () => {
    localStorage.setItem('right-panel-auto-collapse-sidebar', '1');
    useRightPanelStore.getState().setOpen(false);
    renderLayout();
    expect(sidebarCollapsed()).toBe(false);
  });

  it('右栏最大化时即使设置关闭也折叠左栏', () => {
    useRightPanelStore.setState({ maximized: true });
    renderLayout();
    expect(sidebarCollapsed()).toBe(true);
  });
});
