// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { I18nProvider } from '../../../shared/lib/i18n';
import { ComponentsTab } from '../ComponentsTab';

function renderTab() {
  return render(
    <I18nProvider defaultLocale="zh">
      <ComponentsTab />
    </I18nProvider>,
  );
}

function installBridge(overrides: Record<string, unknown> = {}) {
  const bridge = {
    list: vi.fn().mockResolvedValue({
      ok: true,
      installed: [
        {
          id: 'embedding-demo',
          name: 'Demo',
          version: '1.0.0',
          target: 'user_data',
          installedAt: '2026-11-17T00:00:00Z',
          fileCount: 1,
          totalBytes: 10,
          sourcePackage: '/tmp/demo.sagepkg',
          signatureVerified: true,
        },
      ],
      discovered: [],
    }),
    scan: vi.fn().mockResolvedValue({
      ok: true,
      discovered: [
        {
          path: '/tmp/ocr.sagepkg',
          id: 'ocr-demo',
          name: 'OCR',
          version: '1.0.0',
          size: 100,
        },
      ],
    }),
    pickAndImport: vi.fn().mockResolvedValue({ ok: true }),
    importPath: vi.fn().mockResolvedValue({ ok: true }),
    remove: vi.fn().mockResolvedValue({ ok: true, componentId: 'embedding-demo' }),
    ...overrides,
  };
  (window as { electronAPI?: unknown }).electronAPI = {
    components: bridge,
    listen: vi.fn().mockResolvedValue(() => {}),
  };
  return bridge;
}

describe('ComponentsTab', () => {
  afterEach(() => {
    delete (window as { electronAPI?: unknown }).electronAPI;
    vi.restoreAllMocks();
  });

  it('renders installed components and imports a package', async () => {
    const bridge = installBridge();
    renderTab();

    expect(await screen.findByText('Demo')).toBeInTheDocument();
    expect(screen.getByText(/签名已验证/)).toBeInTheDocument();

    fireEvent.click(screen.getByTestId('components-import'));
    await waitFor(() => expect(bridge.pickAndImport).toHaveBeenCalledTimes(1));
    expect(await screen.findByText(/导入完成/)).toBeInTheDocument();
  });

  it('scans and imports a discovered package path', async () => {
    const bridge = installBridge();
    renderTab();
    await screen.findByText('Demo');

    fireEvent.click(screen.getByTestId('components-scan'));
    await waitFor(() => expect(bridge.scan).toHaveBeenCalledTimes(1));
    expect(await screen.findByText('OCR 1.0.0')).toBeInTheDocument();

    fireEvent.click(screen.getByTestId('components-import-0'));
    await waitFor(() => expect(bridge.importPath).toHaveBeenCalledWith('/tmp/ocr.sagepkg'));
  });

  it('removes an installed component after confirmation', async () => {
    const bridge = installBridge();
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    renderTab();
    await screen.findByText('Demo');

    fireEvent.click(screen.getByTestId('components-remove-embedding-demo'));
    await waitFor(() => expect(bridge.remove).toHaveBeenCalledWith('embedding-demo'));
  });

  it('shows a desktop-only notice without the bridge', () => {
    renderTab();
    expect(screen.getByText(/仅在 Sage 桌面端可用/)).toBeInTheDocument();
  });
});
