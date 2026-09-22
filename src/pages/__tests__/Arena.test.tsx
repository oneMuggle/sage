/**
 * Arena 控制台页面测试 (2026-09-19, P5)
 *
 * - 三页签渲染与切换（账号池 / 批量注册 / 抽卡）
 * - 账号池默认渲染账号表；403 显示启用指引
 * - 抽卡页签含 token 窗口状态卡
 *
 * 策略与 ArenaAccounts.test.tsx 一致：mock entities/arena 模块。
 */
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { I18nProvider } from '../../shared/lib/i18n';

const mocks = vi.hoisted(() => ({
  listAccounts: vi.fn(),
  createAccount: vi.fn(),
  deleteAccount: vi.fn(),
  isolateAccount: vi.fn(),
  enableAccount: vi.fn(),
  startRegistration: vi.fn(),
  getRegistration: vi.fn(),
  openVerification: vi.fn(),
  setRegistrationPassword: vi.fn(),
  cancelRegistration: vi.fn(),
  listObservations: vi.fn(),
  attachObservation: vi.fn(),
  detachObservation: vi.fn(),
  startRegistrationJob: vi.fn(),
  getRegistrationJob: vi.fn(),
  getRegistrationJobEvents: vi.fn(),
  stopRegistrationJob: vi.fn(),
  exportRegistrationJob: vi.fn(),
  startDrawJob: vi.fn(),
  listDrawJobs: vi.fn(),
  getDrawJob: vi.fn(),
  stopDrawJob: vi.fn(),
  getDrawJobEvents: vi.fn(),
  listDraws: vi.fn(),
  tokenWindowHealth: vi.fn(),
  tokenWindowState: vi.fn(),
}));

vi.mock('../../entities/arena', () => mocks);

beforeEach(() => {
  (window as unknown as { electronAPI?: unknown }).electronAPI = {
    backendRequest: async () => null,
  };
  mocks.listObservations.mockResolvedValue({ attached: false, verdicts: [] });
  mocks.listDraws.mockResolvedValue([]);
  mocks.tokenWindowHealth.mockResolvedValue({
    ready: false, count: 0, error: '', exit_ip: '', ua: '', uptime: 0, last_push_age: null,
  });
  mocks.tokenWindowState.mockResolvedValue({
    enabled: false, needed: false, reject_count: 0, want_proxy: false,
    proxy_url: '', poll_interval_sec: 2,
  });
});

afterEach(() => {
  vi.restoreAllMocks();
  for (const fn of Object.values(mocks)) fn.mockReset();
});

function renderPage() {
  return import('../Arena').then((m) =>
    render(
      <MemoryRouter initialEntries={['/arena']}>
        <I18nProvider>
          <m.default />
        </I18nProvider>
      </MemoryRouter>,
    ),
  );
}

const SAMPLE_ACCOUNT = {
  id: 'acc-1',
  email: 'user1@example.com',
  state: 'available',
  failure_count: 0,
  last_used_at: null,
  isolated_at: null,
  created_at: '2026-09-19T00:00:00',
  notes: null,
};

describe('Arena page', () => {
  it('默认账号池页签渲染账号行与三个页签入口', async () => {
    mocks.listAccounts.mockResolvedValue([SAMPLE_ACCOUNT]);
    renderPage();
    expect(await screen.findByTestId('account-row-user1@example.com')).toBeInTheDocument();
    expect(screen.getByTestId('arena-tab-accounts')).toBeInTheDocument();
    expect(screen.getByTestId('arena-tab-register')).toBeInTheDocument();
    expect(screen.getByTestId('arena-tab-draw')).toBeInTheDocument();
  });

  it('切到批量注册页签显示批量面板', async () => {
    mocks.listAccounts.mockResolvedValue([]);
    renderPage();
    fireEvent.click(await screen.findByTestId('arena-tab-register'));
    expect(await screen.findByTestId('batch-register-panel')).toBeInTheDocument();
  });

  it('切到抽卡页签显示 token 窗口卡与抽卡面板', async () => {
    mocks.listAccounts.mockResolvedValue([]);
    mocks.listDraws.mockResolvedValue([
      {
        account_id: 'acc-1', email: 'user1@example.com', model: 'GPT-6 Astra', internal: '',
        provider: '', session_id: 's1', run_id: 'run_42', kept: true, ok: true, error: '',
        reasoning: 1, tokens_in: 1, tokens_out: 1, tier: '', setting_hints: '', switch: false,
        created_at: '2026-09-19T12:00:00',
      },
    ]);
    renderPage();
    fireEvent.click(await screen.findByTestId('arena-tab-draw'));
    expect(await screen.findByTestId('token-window-card')).toBeInTheDocument();
    expect(await screen.findByTestId('draw-panel')).toBeInTheDocument();
    expect(await screen.findByTestId('draws-table')).toBeInTheDocument();
  });

  it('后端 403 时账号池页签显示启用指引', async () => {
    const { BackendRequestError } = await import('../../shared/api/backendRequest');
    mocks.listAccounts.mockRejectedValue(new BackendRequestError(403, 'arena automation is disabled'));
    renderPage();
    const note = await screen.findByTestId('arena-error');
    expect(note.textContent).toContain('未启用');
    expect(screen.queryByTestId('register-assist')).not.toBeInTheDocument();
  });
});
