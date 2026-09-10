// @vitest-environment jsdom
import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { I18nProvider } from '../../../shared/lib/i18n';
import { ProvidersManager } from '../ProvidersManager';

const mocks = vi.hoisted(() => ({
  list: vi.fn(),
  setDefault: vi.fn(),
  test: vi.fn(),
  remove: vi.fn(),
  add: vi.fn(),
  get: vi.fn(),
  update: vi.fn(),
}));

const defaultList = [
  { id: 'a', type: 'github' as const, displayName: 'G1', enabled: true, isDefault: true, config: {} },
  { id: 'b', type: 'gitee' as const, displayName: 'G2', enabled: true, isDefault: false, config: {} },
];

beforeEach(() => {
  mocks.list.mockReset().mockResolvedValue(defaultList);
  mocks.setDefault.mockReset().mockResolvedValue({ ok: true });
  mocks.test.mockReset().mockResolvedValue({ ok: true, latencyMs: 42 });
  mocks.remove.mockReset().mockResolvedValue({ ok: true });
  mocks.add.mockReset().mockResolvedValue({ id: 'new-id' });
  mocks.get.mockReset();
  mocks.update.mockReset().mockResolvedValue({ ok: true });
  (window as unknown as { electronAPI?: unknown }).electronAPI = {
    providers: {
      list: mocks.list,
      get: mocks.get,
      add: mocks.add,
      update: mocks.update,
      remove: mocks.remove,
      setDefault: mocks.setDefault,
      test: mocks.test,
    },
    updates: {},
  };
});

function renderManager(): void {
  render(
    <I18nProvider>
      <ProvidersManager />
    </I18nProvider>,
  );
}

describe('ProvidersManager', () => {
  it('renders provider list with default highlighted', async () => {
    renderManager();

    await waitFor(() => expect(mocks.list).toHaveBeenCalledOnce());
    expect(await screen.findByTestId('provider-row-a')).toBeInTheDocument();
    expect(screen.getByTestId('provider-row-b')).toBeInTheDocument();
    expect(screen.getByText('默认')).toBeInTheDocument();
    // Set-default only on non-default rows
    expect(screen.getByTestId('provider-set-default-b')).toBeInTheDocument();
    expect(screen.queryByTestId('provider-set-default-a')).not.toBeInTheDocument();
  });

  it('shows the current default in the caption', async () => {
    renderManager();

    await screen.findByTestId('provider-row-a');
    expect(screen.getByTestId('providers-current-default').textContent).toContain('G1');
  });

  it('disables remove button on the default provider', async () => {
    renderManager();

    await screen.findByTestId('provider-row-a');
    expect(screen.getByTestId('provider-remove-a')).toBeDisabled();
    expect(screen.getByTestId('provider-remove-b')).not.toBeDisabled();
  });

  it('invokes setDefault and refreshes on click', async () => {
    renderManager();
    await screen.findByTestId('provider-row-b');

    const btn = screen.getByTestId('provider-set-default-b');
    btn.click();

    await waitFor(() => expect(mocks.setDefault).toHaveBeenCalledWith('b'));
  });
});