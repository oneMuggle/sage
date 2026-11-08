/**
 * /office 路由复用侧栏内容列 —— 侧栏侧行为。
 *
 * 覆盖：
 *   - `/office` 下内容列只保留品牌头 / office slot / 状态栏，会话导航不渲染；
 *   - 其他路由保持原有 primary actions + 会话 nav；
 *   - 折叠态内容列卸载后 slotEl 归 null（Office 据此回退内联两栏）。
 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, useNavigate } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { I18nProvider } from '../../../shared/lib/i18n';
import { useStore } from '../../../shared/lib/store';
import { Sidebar } from '../Sidebar';
import { SidebarSlotProvider, useSidebarSlot } from '../SidebarSlotProvider';

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

// 把 Provider 内的 slotEl 暴露给断言：非空说明 Sidebar 的 slot 容器已挂载。
function SlotProbe() {
  const { slotEl } = useSidebarSlot();
  return <span data-testid="slot-probe" data-has-slot={slotEl ? 'yes' : 'no'} />;
}

function NavProbe() {
  const navigate = useNavigate();
  return (
    <button type="button" data-testid="nav-to-chat" onClick={() => navigate('/chat')}>
      chat
    </button>
  );
}

function sidebarTree(path: string, collapsed = false) {
  return (
    <I18nProvider defaultLocale="zh">
      <MemoryRouter initialEntries={[path]}>
        <SidebarSlotProvider>
          <Sidebar width={300} collapsed={collapsed} />
          <SlotProbe />
          <NavProbe />
        </SidebarSlotProvider>
      </MemoryRouter>
    </I18nProvider>
  );
}

describe('Sidebar — /office 内容列插槽', () => {
  it('/office 渲染 office slot，会话导航与 primary actions 不渲染', () => {
    render(sidebarTree('/office'));
    expect(screen.getByTestId('sidebar-office-slot')).toBeInTheDocument();
    expect(screen.queryByTestId('sidebar-primary-actions')).toBeNull();
    expect(screen.queryByTestId('sidebar-scroll')).toBeNull();
    // 品牌头与底部状态栏保留，侧栏视觉连续
    expect(screen.getByTestId('sidebar-content')).toBeInTheDocument();
    expect(screen.getByTestId('slot-probe').getAttribute('data-has-slot')).toBe('yes');
  });

  it('其他路由保持原有导航，且不渲染 office slot', () => {
    render(sidebarTree('/chat'));
    expect(screen.queryByTestId('sidebar-office-slot')).toBeNull();
    expect(screen.getByTestId('sidebar-primary-actions')).toBeInTheDocument();
    expect(screen.getByTestId('sidebar-scroll')).toBeInTheDocument();
    expect(screen.getByTestId('slot-probe').getAttribute('data-has-slot')).toBe('no');
  });

  it('折叠时内容列卸载，slotEl 归 null（供 Office 回退内联两栏）', () => {
    const { rerender } = render(sidebarTree('/office'));
    expect(screen.getByTestId('slot-probe').getAttribute('data-has-slot')).toBe('yes');

    rerender(sidebarTree('/office', true));

    expect(screen.queryByTestId('sidebar-content')).toBeNull();
    expect(screen.queryByTestId('sidebar-office-slot')).toBeNull();
    expect(screen.getByTestId('slot-probe').getAttribute('data-has-slot')).toBe('no');
  });

  it('从 /office 切到其他路由后 slotEl 归 null，导航恢复', async () => {
    render(sidebarTree('/office'));
    expect(screen.getByTestId('slot-probe').getAttribute('data-has-slot')).toBe('yes');

    fireEvent.click(screen.getByTestId('nav-to-chat'));

    await waitFor(() =>
      expect(screen.getByTestId('slot-probe').getAttribute('data-has-slot')).toBe('no'),
    );
    expect(screen.queryByTestId('sidebar-office-slot')).toBeNull();
    expect(screen.getByTestId('sidebar-primary-actions')).toBeInTheDocument();
  });
});
