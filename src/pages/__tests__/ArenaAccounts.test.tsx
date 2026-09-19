/**
 * ArenaAccounts 页面测试 (2026-09-19)
 *
 * 验证账号管理页核心契约:
 * - 账号列表加载 → 显示账号行（邮箱/状态/动作）
 * - 隔离/启用/删除动作 → 调用对应 API 并刷新
 * - 403（功能未启用）→ 显示启用指引而非裸错误
 * - 注册向导: start → 状态展示; verification_ready → 显示打开链接按钮
 *
 * 测试策略与 ModelCatalog.test.tsx 一致: mock entities/arena/api 模块。
 */
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { I18nProvider } from '../../shared/lib/i18n';

const mocks = vi.hoisted(() => {
  const createMock = () => vi.fn();
  return {
    listAccounts: createMock(),
    createAccount: createMock(),
    deleteAccount: createMock(),
    isolateAccount: createMock(),
    enableAccount: createMock(),
    startRegistration: createMock(),
    getRegistration: createMock(),
    openVerification: createMock(),
    setRegistrationPassword: createMock(),
    cancelRegistration: createMock(),
    listObservations: createMock(),
    attachObservation: createMock(),
    detachObservation: createMock(),
  };
});

vi.mock('../../entities/arena/api', () => ({
  listAccounts: mocks.listAccounts,
  createAccount: mocks.createAccount,
  deleteAccount: mocks.deleteAccount,
  isolateAccount: mocks.isolateAccount,
  enableAccount: mocks.enableAccount,
  startRegistration: mocks.startRegistration,
  getRegistration: mocks.getRegistration,
  openVerification: mocks.openVerification,
  setRegistrationPassword: mocks.setRegistrationPassword,
  cancelRegistration: mocks.cancelRegistration,
  listObservations: mocks.listObservations,
  attachObservation: mocks.attachObservation,
  detachObservation: mocks.detachObservation,
}));

// BackendRequestError 由 shared/api/backendRequest 导出 —— 保留真实实现,
// 仅桩化 electronAPI（页面 import BackendRequestError 做状态判断）。
beforeEach(() => {
  (window as unknown as { electronAPI?: unknown }).electronAPI = {
    backendRequest: async () => null,
  };
  mocks.listObservations.mockResolvedValue({ attached: false, verdicts: [] });
  window.confirm = vi.fn(() => true);
});

afterEach(() => {
  vi.restoreAllMocks();
  for (const key of Object.keys(mocks)) {
    (mocks as unknown as Record<string, ReturnType<typeof vi.fn>>)[key].mockReset();
  }
});

function renderPage() {
  // 延迟 import，保证 vi.mock 生效后再加载页面模块
  return import('../ArenaAccounts').then((m) =>
    render(
      <MemoryRouter>
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

describe('ArenaAccounts page', () => {
  it('加载后显示账号行', async () => {
    mocks.listAccounts.mockResolvedValue([SAMPLE_ACCOUNT]);
    renderPage();
    expect(await screen.findByTestId('account-row-user1@example.com')).toBeInTheDocument();
    expect(screen.getByText('可用')).toBeInTheDocument();
  });

  it('空账号池显示空态提示', async () => {
    mocks.listAccounts.mockResolvedValue([]);
    renderPage();
    expect(await screen.findByTestId('account-table-empty')).toBeInTheDocument();
  });

  it('后端 403 时显示启用指引', async () => {
    const { BackendRequestError } = await import('../../shared/api/backendRequest');
    mocks.listAccounts.mockRejectedValue(new BackendRequestError(403, 'arena automation is disabled'));
    renderPage();
    const note = await screen.findByTestId('arena-error');
    expect(note.textContent).toContain('未启用');
    // 功能关闭时不渲染主表格/向导
    expect(screen.queryByTestId('register-assist')).not.toBeInTheDocument();
  });

  it('隔离动作调用 API 并刷新列表', async () => {
    mocks.listAccounts
      .mockResolvedValueOnce([{ ...SAMPLE_ACCOUNT, state: 'degraded' }])
      .mockResolvedValueOnce([{ ...SAMPLE_ACCOUNT, state: 'disabled' }]);
    mocks.isolateAccount.mockResolvedValue({ ...SAMPLE_ACCOUNT, state: 'disabled' });
    renderPage();
    const row = await screen.findByTestId('account-row-user1@example.com');
    fireEvent.click(within(row).getByTestId('account-isolate-acc-1'));
    await waitFor(() => expect(mocks.isolateAccount).toHaveBeenCalledWith('acc-1'));
    await waitFor(() => expect(mocks.listAccounts).toHaveBeenCalledTimes(2));
  });

  it('注册向导：start 后展示状态与人工验证码提示', async () => {
    mocks.listAccounts.mockResolvedValue([]);
    // 挂载恢复请求显式失败（= 无进行中注册），避免与 start 产生竞态
    mocks.getRegistration.mockRejectedValue(new Error('HTTP 404'));
    mocks.startRegistration.mockResolvedValue({
      registration_id: 'reg1',
      email: 'tmp@mail.tm',
      state: 'awaiting_signup',
      captcha_present: true,
      verification_link: '',
      email_filled: true,
      error: '',
      created_at: '2026-09-19T00:00:00',
      expires_in_sec: 1800,
      manual_hint: '请在打开的浏览器中完成人机验证并提交注册表单',
    });
    renderPage();
    fireEvent.click(await screen.findByTestId('register-start'));
    expect(await screen.findByTestId('register-state')).toHaveTextContent('填写注册表单');
    expect(screen.getByTestId('captcha-hint')).toHaveTextContent('手动完成');
    expect(mocks.startRegistration).toHaveBeenCalledTimes(1);
  });

  it('verification_ready 时显示「打开验证链接」按钮', async () => {
    mocks.listAccounts.mockResolvedValue([]);
    mocks.getRegistration.mockResolvedValue({
      registration_id: 'reg2',
      email: 'tmp2@mail.tm',
      state: 'verification_ready',
      captcha_present: false,
      verification_link: 'https://arena.ai/nextjs-api/callback?token=pkce_x',
      email_filled: true,
      error: '',
      created_at: '2026-09-19T00:00:00',
      expires_in_sec: 900,
      manual_hint: '验证邮件已到',
    });
    renderPage();
    await screen.findByTestId('register-status');
    expect(await screen.findByTestId('register-open-verify')).toBeInTheDocument();
  });

  it('观测组件未启动时显示空态', async () => {
    mocks.listAccounts.mockResolvedValue([]);
    renderPage();
    expect(await screen.findByTestId('observation-feed')).toBeInTheDocument();
    expect(screen.getByTestId('observation-empty')).toHaveTextContent('未启动');
  });
});
