// @vitest-environment jsdom
/**
 * BrowserUseSection 契约（M4 前端）：
 * - 挂载时加载 use-config + site-policies
 * - 开关调用 updateBrowserUseConfig
 * - 新增/删除站点策略调用 client；删除前走 confirmDialog
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { I18nProvider } from '../../../shared/lib/i18n';
import { BrowserUseSection } from '../BrowserUseSection';

const mocks = vi.hoisted(() => ({
  fetchBrowserUseConfig: vi.fn(),
  updateBrowserUseConfig: vi.fn(),
  fetchSitePolicies: vi.fn(),
  setSitePolicy: vi.fn(),
  deleteSitePolicy: vi.fn(),
  confirmDialog: vi.fn(),
}));

vi.mock('../../../shared/api/browserControlClient', () => ({
  fetchBrowserUseConfig: (...args: unknown[]) => mocks.fetchBrowserUseConfig(...args),
  updateBrowserUseConfig: (...args: unknown[]) => mocks.updateBrowserUseConfig(...args),
  fetchSitePolicies: (...args: unknown[]) => mocks.fetchSitePolicies(...args),
  setSitePolicy: (...args: unknown[]) => mocks.setSitePolicy(...args),
  deleteSitePolicy: (...args: unknown[]) => mocks.deleteSitePolicy(...args),
}));

vi.mock('../../../shared/ui/ConfirmDialog/confirmService', () => ({
  confirmDialog: (...args: unknown[]) => mocks.confirmDialog(...args),
}));

vi.mock('sonner', () => ({
  toast: { error: vi.fn(), success: vi.fn(), info: vi.fn() },
}));

function renderSection(): ReturnType<typeof render> {
  return render(
    <I18nProvider>
      <BrowserUseSection />
    </I18nProvider>,
  );
}

beforeEach(() => {
  Object.values(mocks).forEach((fn) => fn.mockReset());
  mocks.fetchBrowserUseConfig.mockResolvedValue({
    default_visible: true,
    step_thumbnails: true,
  });
  mocks.fetchSitePolicies.mockResolvedValue([]);
  mocks.updateBrowserUseConfig.mockImplementation(async (patch: Record<string, boolean>) => ({
    default_visible: true,
    step_thumbnails: true,
    ...patch,
  }));
  mocks.setSitePolicy.mockResolvedValue({
    domain: 'example.com',
    mode: 'allow',
    updated_at: 1,
  });
  mocks.deleteSitePolicy.mockResolvedValue(undefined);
  mocks.confirmDialog.mockResolvedValue(true);
});

describe('BrowserUseSection', () => {
  it('加载 use-config 与站点策略并渲染开关和表格', async () => {
    mocks.fetchBrowserUseConfig.mockResolvedValue({
      default_visible: false,
      step_thumbnails: true,
    });
    mocks.fetchSitePolicies.mockResolvedValue([
      { domain: 'example.com', mode: 'block', updated_at: 1_700_000_000_000 },
    ]);
    renderSection();

    const row = await screen.findByTestId('site-policy-row-example.com');
    expect(row.textContent).toContain('example.com');
    expect(row.textContent).toContain('禁止');
    expect(
      (await screen.findByTestId('browser-use-default-visible')).getAttribute('aria-checked'),
    ).toBe('false');
    expect(screen.getByTestId('browser-use-step-thumbnails').getAttribute('aria-checked')).toBe(
      'true',
    );
    expect(screen.queryByTestId('site-policy-empty')).toBeNull();
  });

  it('无策略时展示空态文案', async () => {
    renderSection();
    expect((await screen.findByTestId('site-policy-empty')).textContent).toContain(
      '暂无站点策略。浏览新站点时 Sage 会先征求授权。',
    );
  });

  it('切换开关调用 updateBrowserUseConfig', async () => {
    renderSection();
    fireEvent.click(await screen.findByTestId('browser-use-default-visible'));
    await waitFor(() =>
      expect(mocks.updateBrowserUseConfig).toHaveBeenCalledWith({ default_visible: false }),
    );
    expect(screen.getByTestId('browser-use-default-visible').getAttribute('aria-checked')).toBe(
      'false',
    );
  });

  it('新增站点策略调用 setSitePolicy 并刷新列表', async () => {
    mocks.fetchSitePolicies
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([{ domain: 'example.com', mode: 'block', updated_at: 2 }]);
    renderSection();
    fireEvent.change(await screen.findByTestId('site-policy-domain'), {
      target: { value: 'Example.COM.' },
    });
    fireEvent.change(screen.getByTestId('site-policy-mode'), { target: { value: 'block' } });
    fireEvent.click(screen.getByTestId('site-policy-add'));

    await waitFor(() => expect(mocks.setSitePolicy).toHaveBeenCalledWith('example.com', 'block'));
    expect(await screen.findByTestId('site-policy-row-example.com')).toBeTruthy();
  });

  it('确认后删除站点策略调用 deleteSitePolicy', async () => {
    mocks.fetchSitePolicies.mockResolvedValue([
      { domain: 'example.com', mode: 'allow', updated_at: 1 },
    ]);
    renderSection();
    fireEvent.click(await screen.findByTestId('site-policy-delete-example.com'));

    await waitFor(() => expect(mocks.confirmDialog).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(mocks.deleteSitePolicy).toHaveBeenCalledWith('example.com'));
    await waitFor(() => expect(screen.queryByTestId('site-policy-row-example.com')).toBeNull());
  });

  it('取消确认时不删除', async () => {
    mocks.fetchSitePolicies.mockResolvedValue([
      { domain: 'example.com', mode: 'allow', updated_at: 1 },
    ]);
    mocks.confirmDialog.mockResolvedValue(false);
    renderSection();
    fireEvent.click(await screen.findByTestId('site-policy-delete-example.com'));

    await waitFor(() => expect(mocks.confirmDialog).toHaveBeenCalledTimes(1));
    expect(mocks.deleteSitePolicy).not.toHaveBeenCalled();
    expect(screen.getByTestId('site-policy-row-example.com')).toBeTruthy();
  });
});
