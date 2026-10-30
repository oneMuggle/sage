// src/widgets/settings/__tests__/HookHistoryPanel.pluginOwner.test.tsx
//
// R115: Hook 历史行插件归属后缀 —— 名单命中时在工具名后追加
// 「（所属插件: <name>）」，读不到/内置工具不加。名单供数由
// usePluginNames 承担（其契约在 hook 套件），这里 mock 其
// 返回值 + backendRequest 测渲染结合。

import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { HookHistoryPanel } from '../HookHistoryPanel';

const mockBackendRequest = vi.fn();
const usePluginNamesMock = vi.fn();

vi.mock('../../../shared/api/backendRequest', () => ({
  backendRequest: (request: unknown) => mockBackendRequest(request),
}));

vi.mock('../../../shared/lib/hooks/usePluginNames', () => ({
  usePluginNames: (...a: unknown[]) => usePluginNamesMock(...a),
}));

const RECORDS = [
  {
    id: '1',
    occurred_at: '2026-10-28T00:00:00Z',
    hook_id: 'audit_log',
    hook_type: 'python',
    event: 'post_tool_use',
    tool_name: 'plugin__demo__echo',
    decision: 'allow',
    duration_ms: 3,
  },
  {
    id: '2',
    occurred_at: '2026-10-28T00:01:00Z',
    hook_id: 'security_guard',
    hook_type: 'python',
    event: 'pre_tool_use',
    tool_name: 'bash',
    decision: 'deny',
    duration_ms: 5,
  },
];

beforeEach(() => {
  vi.clearAllMocks();
  mockBackendRequest.mockResolvedValue({ records: RECORDS });
  usePluginNamesMock.mockReturnValue(null);
});

describe('HookHistoryPanel 插件归属（R115）', () => {
  it('插件工具行显示归属后缀，内置行不带', async () => {
    usePluginNamesMock.mockReturnValue(['demo']);
    render(<HookHistoryPanel />);
    await waitFor(() =>
      expect(screen.getByText(/plugin__demo__echo（所属插件: demo）/)).toBeInTheDocument(),
    );
    expect(usePluginNamesMock).toHaveBeenCalledWith(true);
    const bashRow = screen.getByText(/security_guard → bash/);
    expect(bashRow).not.toHaveTextContent('所属插件');
  });

  it('名单不可用时不加后缀', async () => {
    render(<HookHistoryPanel />);
    await waitFor(() => expect(screen.getByText(/plugin__demo__echo/)).toBeInTheDocument());
    expect(screen.getByTestId('hook-history-panel')).not.toHaveTextContent('所属插件');
  });
});
