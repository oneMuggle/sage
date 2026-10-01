// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const getTrustPolicy = vi.fn();
const setTrustPolicy = vi.fn();

vi.mock('../../../shared/api/permissionApi', () => ({
  permissionApi: {
    getTrustPolicy: () => getTrustPolicy(),
    setTrustPolicy: (enabled: boolean, threshold?: number) =>
      setTrustPolicy(enabled, threshold),
  },
}));

import { I18nProvider } from '../../../shared/lib/i18n';
import { ToolsConnectionsTab } from '../ToolsConnectionsTab';

const DISABLED = { enabled: false, threshold: 3, default_threshold: 3, consecutive: {} };
const ENABLED = {
  enabled: true,
  threshold: 3,
  default_threshold: 3,
  consecutive: { 's1|bash': 3, 's1|edit_file': 1 },
};

beforeEach(() => {
  getTrustPolicy.mockReset();
  setTrustPolicy.mockReset();
  getTrustPolicy.mockResolvedValue(DISABLED);
  setTrustPolicy.mockImplementation(async (enabled: boolean, threshold?: number) => ({
    ...DISABLED,
    enabled,
    threshold: threshold ?? 3,
  }));
});

/** 只渲染权限那一段，避免 hooks/gateway 的副作用干扰断言 */
function renderTab() {
  return render(
    <I18nProvider defaultLocale="zh">
      <ToolsConnectionsTab />
    </I18nProvider>,
  );
}

describe('渐进式授权设置 (P2-5)', () => {
  it('默认关闭 —— 未经用户同意的自动放行不允许存在', async () => {
    renderTab();
    await waitFor(() => expect(getTrustPolicy).toHaveBeenCalled());
    const toggle = await screen.findByTestId('trust-escalation-toggle');
    expect(toggle).toHaveAttribute('aria-checked', 'false');
  });

  it('回填后端已有的启用状态与阈值', async () => {
    getTrustPolicy.mockResolvedValue({ ...ENABLED, threshold: 5 });
    renderTab();
    const toggle = await screen.findByTestId('trust-escalation-toggle');
    await waitFor(() => expect(toggle).toHaveAttribute('aria-checked', 'true'));
    expect((screen.getByTestId('trust-escalation-threshold') as HTMLInputElement).value).toBe('5');
  });

  it('打开开关才展示阈值输入 —— 关闭时不该有可调项', async () => {
    renderTab();
    await screen.findByTestId('trust-escalation-toggle');
    expect(screen.queryByTestId('trust-escalation-threshold')).not.toBeInTheDocument();
  });

  it('切换开关会落库', async () => {
    renderTab();
    const toggle = await screen.findByTestId('trust-escalation-toggle');
    // 不用 act(async) 包裹：ToolsConnectionsTab 里的 Gateway/Hooks 卡片会发起
    // 未 mock 的 invoke，永远不 resolve，会把 act 的作用域一直吊着直到超时。
    fireEvent.click(toggle);
    await waitFor(() => expect(setTrustPolicy).toHaveBeenCalledWith(true, 3));
  });

  it('显示已积累的信任，让用户看得见「凭什么替我点同意」', async () => {
    getTrustPolicy.mockResolvedValue(ENABLED);
    renderTab();
    const list = await screen.findByTestId('trust-escalation-trust-list');
    expect(list).toHaveTextContent('bash · 3');
    expect(list).toHaveTextContent('已达阈值');
    expect(list).toHaveTextContent('edit_file · 1');
  });

  it('未达阈值的工具不标「已达阈值」', async () => {
    getTrustPolicy.mockResolvedValue(ENABLED);
    renderTab();
    const list = await screen.findByTestId('trust-escalation-trust-list');
    expect(list.textContent?.match(/已达阈值/g)).toHaveLength(1);
  });

  it('写失败时如实报错，并回滚开关状态（不让 UI 显示「开」而后端没开）', async () => {
    getTrustPolicy.mockResolvedValue(DISABLED);
    setTrustPolicy.mockRejectedValue(new Error('数据库只读'));
    renderTab();
    const toggle = await screen.findByTestId('trust-escalation-toggle');
    fireEvent.click(toggle);
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('数据库只读');
    await waitFor(() => expect(toggle).toHaveAttribute('aria-checked', 'false'));
  });

  it('读取失败时显示错误而不是假装策略已加载', async () => {
    getTrustPolicy.mockRejectedValue(new Error('后端不可达'));
    renderTab();
    expect(await screen.findByRole('alert')).toHaveTextContent('后端不可达');
  });

  it('文案说明危险操作仍然逐次询问，不夸大承诺', async () => {
    renderTab();
    const section = await screen.findByTestId('trust-escalation-section');
    expect(section).toHaveTextContent('破坏性命令');
    expect(section).toHaveTextContent('逐次询问');
  });
});
