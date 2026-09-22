/**
 * DrawPanel / TokenWindowCard 测试 (2026-09-19, P5)
 *
 * DrawPanel:
 * - 全部账号模式启动 → startDrawJob 携带正确参数
 * - 勾选模式 → account_ids 传递所选账号
 * - 抽卡记录表渲染
 * TokenWindowCard:
 * - health/state 轮询渲染就绪态 / 出口 IP / 需要出票
 * - 403 → 显示启用指引
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  listAccounts: vi.fn(),
  listDraws: vi.fn(),
  startDrawJob: vi.fn(),
  tokenWindowHealth: vi.fn(),
  tokenWindowState: vi.fn(),
}));

vi.mock('../../../entities/arena', () => mocks);

import { DrawPanel } from '../DrawPanel';
import { TokenWindowCard } from '../TokenWindowCard';

const ACCOUNT = { id: 'acc-1', email: 'user1@example.com', state: 'available', failure_count: 0, last_used_at: null, isolated_at: null, created_at: '2026-09-19T00:00:00', notes: null };
const DRAW_ROW = {
  account_id: 'acc-1', email: 'user1@example.com', model: 'GPT-6 Astra', internal: 'gpt-6-astra-low',
  provider: '', session_id: 's1', run_id: 'run_42', kept: true, ok: true, error: '',
  reasoning: 123, tokens_in: 10, tokens_out: 5, tier: 'low', setting_hints: '', switch: false,
  created_at: '2026-09-19T12:34:56',
};

afterEach(() => {
  vi.restoreAllMocks();
  for (const fn of Object.values(mocks)) fn.mockReset();
});

describe('DrawPanel', () => {
  it('全部账号模式启动携带默认参数', async () => {
    mocks.listAccounts.mockResolvedValue([ACCOUNT]);
    mocks.listDraws.mockResolvedValue([]);
    mocks.startDrawJob.mockResolvedValue({ id: 'dj-1', status: 'running' });

    render(<DrawPanel />);
    fireEvent.click(await screen.findByTestId('draw-start'));

    await waitFor(() =>
      expect(mocks.startDrawJob).toHaveBeenCalledWith({
        all_accounts: true,
        account_ids: undefined,
        rounds_per_account: 1,
        keep_pattern: '',
        miss_action: 'archive',
        rename_hit: false,
        want_reasoning: true,
      }),
    );
  });

  it('勾选模式传递所选账号', async () => {
    mocks.listAccounts.mockResolvedValue([ACCOUNT, { ...ACCOUNT, id: 'acc-2', email: 'u2@x.c' }]);
    mocks.listDraws.mockResolvedValue([]);
    mocks.startDrawJob.mockResolvedValue({ id: 'dj-2', status: 'running' });

    render(<DrawPanel />);
    fireEvent.click(await screen.findByTestId('draw-all-accounts'), { target: { } });
    // 取消勾选「全部」 → 出现账号选择器
    const picker = await screen.findByTestId('draw-account-picker');
    expect(picker).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('draw-account-acc-1'));
    fireEvent.click(screen.getByTestId('draw-start'));

    await waitFor(() =>
      expect(mocks.startDrawJob).toHaveBeenCalledWith(
        expect.objectContaining({ all_accounts: false, account_ids: ['acc-1'] }),
      ),
    );
  });

  it('抽卡记录表渲染最近结果', async () => {
    mocks.listAccounts.mockResolvedValue([]);
    mocks.listDraws.mockResolvedValue([DRAW_ROW]);

    render(<DrawPanel />);
    const row = await screen.findByTestId('draws-row-0');
    expect(row).toHaveTextContent('GPT-6 Astra');
    expect(row).toHaveTextContent('user1@example.com');
  });
});

describe('TokenWindowCard', () => {
  it('轮询渲染就绪态与出口信息', async () => {
    mocks.tokenWindowHealth.mockResolvedValue({
      ready: true, count: 6, error: '', exit_ip: '203.0.113.7',
      ua: 'Mozilla/5.0 Chrome/106', uptime: 120, last_push_age: 1,
    });
    mocks.tokenWindowState.mockResolvedValue({
      enabled: true, needed: true, reject_count: 1, want_proxy: false,
      proxy_url: '', poll_interval_sec: 2,
    });

    render(<TokenWindowCard pollIntervalMs={10} />);
    expect(await screen.findByTestId('tw-ready')).toHaveTextContent('就绪');
    expect(screen.getByTestId('tw-count')).toHaveTextContent('6');
    expect(screen.getByTestId('tw-exit-ip')).toHaveTextContent('203.0.113.7');
    expect(screen.getByTestId('tw-needed')).toHaveTextContent('是');
    expect(screen.getByTestId('tw-rejects')).toHaveTextContent('1');
  });

  it('403 显示启用指引', async () => {
    const { BackendRequestError } = await import('../../../shared/api/backendRequest');
    mocks.tokenWindowHealth.mockRejectedValue(new BackendRequestError(403, 'disabled'));
    mocks.tokenWindowState.mockRejectedValue(new BackendRequestError(403, 'disabled'));

    render(<TokenWindowCard pollIntervalMs={10} />);
    expect(await screen.findByTestId('tw-disabled')).toHaveTextContent('token_window.enabled');
  });
});
