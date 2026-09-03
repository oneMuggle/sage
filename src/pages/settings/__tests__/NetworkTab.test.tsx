// @vitest-environment jsdom
/**
 * NetworkTab 契约（内网 Web 访问 Task 7）。
 *
 * 配置走 preferences KV 的 network_policy key（JSON 字符串），与
 * permission_mode 同一路径 —— 不进 app_settings blob（后者有 LEGAL_TOP_KEYS
 * 白名单，加字段要同步改前后端三处）。
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { I18nProvider } from '../../../shared/lib/i18n';
import { NetworkTab } from '../NetworkTab';

const mocks = vi.hoisted(() => ({
  getPreference: vi.fn(),
  setPreference: vi.fn(),
}));

vi.mock('../../../shared/api/settingsClient', () => ({
  LOAD_TIMEOUT_MS: 5000,
  settingsClient: {
    getPreference: (...args: unknown[]) => mocks.getPreference(...args),
    setPreference: (...args: unknown[]) => mocks.setPreference(...args),
  },
}));

function renderTab(): void {
  render(
    <I18nProvider>
      <NetworkTab />
    </I18nProvider>,
  );
}

function lastSavedPolicy(): Record<string, unknown> {
  const calls = mocks.setPreference.mock.calls;
  expect(calls.length).toBeGreaterThan(0);
  const [key, value] = calls[calls.length - 1];
  expect(key).toBe('network_policy');
  return JSON.parse(value as string);
}

describe('NetworkTab', () => {
  beforeEach(() => {
    mocks.getPreference.mockReset();
    mocks.setPreference.mockReset();
    mocks.getPreference.mockResolvedValue(null);
    mocks.setPreference.mockResolvedValue(undefined);
  });

  it('defaults to online when no stored policy', async () => {
    renderTab();
    await waitFor(() => {
      expect(screen.getByTestId('network-mode-select')).toHaveValue('online');
    });
  });

  it('loads stored mode and hosts', async () => {
    mocks.getPreference.mockResolvedValue(
      JSON.stringify({
        mode: 'intranet',
        allowed_hosts: ['*.example.internal', 'docs.example.internal'],
        insecure_tls_hosts: ['docs.example.internal'],
      }),
    );
    renderTab();

    await waitFor(() => {
      expect(screen.getByTestId('network-mode-select')).toHaveValue('intranet');
    });
    expect(screen.getByText('*.example.internal')).toBeTruthy();
    expect(screen.getAllByText('docs.example.internal').length).toBeGreaterThan(0);
  });

  it('persists mode change as JSON under network_policy key', async () => {
    renderTab();
    await waitFor(() => screen.getByTestId('network-mode-select'));

    fireEvent.change(screen.getByTestId('network-mode-select'), {
      target: { value: 'intranet' },
    });

    await waitFor(() => expect(mocks.setPreference).toHaveBeenCalled());
    expect(lastSavedPolicy().mode).toBe('intranet');
  });

  it('adds an allowed host', async () => {
    renderTab();
    await waitFor(() => screen.getByTestId('network-mode-select'));

    fireEvent.change(screen.getByTestId('network-mode-select'), {
      target: { value: 'intranet' },
    });

    await waitFor(() => screen.getByTestId('allowed-host-input'));

    fireEvent.change(screen.getByTestId('allowed-host-input'), {
      target: { value: '*.example.internal' },
    });
    fireEvent.click(screen.getByTestId('allowed-host-add'));

    await waitFor(() => expect(mocks.setPreference).toHaveBeenCalled());
    expect(lastSavedPolicy().allowed_hosts).toEqual(['*.example.internal']);
  });

  it('rejects an overbroad wildcard without saving', async () => {
    renderTab();
    await waitFor(() => screen.getByTestId('network-mode-select'));

    fireEvent.change(screen.getByTestId('network-mode-select'), {
      target: { value: 'intranet' },
    });

    await waitFor(() => screen.getByTestId('allowed-host-input'));

    // 重置 mock，排除切换模式的那次保存
    mocks.setPreference.mockClear();

    fireEvent.change(screen.getByTestId('allowed-host-input'), {
      target: { value: '*.net' },
    });
    fireEvent.click(screen.getByTestId('allowed-host-add'));

    expect(screen.getByTestId('allowed-host-error')).toBeTruthy();
    expect(mocks.setPreference).not.toHaveBeenCalled();
  });

  it('removes an allowed host and drops the TLS exemption it covered', async () => {
    mocks.getPreference.mockResolvedValue(
      JSON.stringify({
        mode: 'intranet',
        allowed_hosts: ['docs.example.internal'],
        insecure_tls_hosts: ['docs.example.internal'],
      }),
    );
    renderTab();
    await waitFor(() => screen.getByTestId('allowed-host-remove-0'));

    fireEvent.click(screen.getByTestId('allowed-host-remove-0'));

    await waitFor(() => expect(mocks.setPreference).toHaveBeenCalled());
    const saved = lastSavedPolicy();
    expect(saved.allowed_hosts).toEqual([]);
    // 后端 __post_init__ 要求 insecure_tls_hosts ⊆ allowed_hosts，
    // 留着孤儿条目会让整份配置被拒并 fail-safe 回 online
    expect(saved.insecure_tls_hosts).toEqual([]);
  });

  it('refuses a TLS exemption not covered by allowed_hosts', async () => {
    renderTab();
    await waitFor(() => screen.getByTestId('network-mode-select'));

    fireEvent.change(screen.getByTestId('network-mode-select'), {
      target: { value: 'intranet' },
    });

    await waitFor(() => screen.getByTestId('insecure-tls-input'));

    // 重置 mock，排除切换模式的那次保存
    mocks.setPreference.mockClear();

    fireEvent.change(screen.getByTestId('insecure-tls-input'), {
      target: { value: 'rogue.example.internal' },
    });
    fireEvent.click(screen.getByTestId('insecure-tls-add'));

    expect(screen.getByTestId('insecure-tls-error')).toBeTruthy();
    expect(mocks.setPreference).not.toHaveBeenCalled();
  });

  it('warns when intranet mode has an empty whitelist', async () => {
    mocks.getPreference.mockResolvedValue(JSON.stringify({ mode: 'intranet' }));
    renderTab();

    await waitFor(() => {
      expect(screen.getByTestId('empty-whitelist-warning')).toBeTruthy();
    });
  });

  it('hides host editors in online mode', async () => {
    renderTab();
    await waitFor(() => screen.getByTestId('network-mode-select'));

    expect(screen.queryByTestId('allowed-host-input')).toBeNull();
  });

  it('survives malformed stored JSON by falling back to online', async () => {
    mocks.getPreference.mockResolvedValue('{not json');
    renderTab();

    await waitFor(() => {
      expect(screen.getByTestId('network-mode-select')).toHaveValue('online');
    });
  });
});
