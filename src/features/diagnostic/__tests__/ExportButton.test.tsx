/**
 * T14: Unit tests for ExportButton component.
 *
 * Tests cover:
 * - Button disabled while export is in progress (busy state)
 * - Success message shows "已导出到 <path>" when result.ok = true
 * - Error messages for each error code: dialog_cancelled,
 *   backend_unreachable, zip_generation_failed, write_failed
 * - Null guard when electronAPI.diagnostic is undefined
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ExportButton } from '../ExportButton';

beforeEach(() => {
  (window as any).electronAPI = {
    diagnostic: {
      exportBundle: vi.fn(),
      preview: vi.fn(),
    },
  };
});

describe('ExportButton', () => {
  it('disables button while export is in progress', async () => {
    let resolveExport: ((v: any) => void) | undefined;
    const pending = new Promise<any>((res) => {
      resolveExport = res;
    });
    (window as any).electronAPI.diagnostic.exportBundle.mockReturnValue(pending);

    render(<ExportButton includePrompts={false} includeHostname={false} />);
    const btn = screen.getByTestId('diagnostic-export-btn');

    expect(btn).not.toBeDisabled();
    fireEvent.click(btn);

    // While the promise is pending the button should be disabled
    expect(btn).toBeDisabled();
    expect(btn).toHaveTextContent('导出中…');

    // Resolve to let the component settle
    resolveExport!({ ok: true, path: '/tmp/x.zip' });
    await waitFor(() => expect(btn).not.toBeDisabled());
  });

  it('shows success message "已导出到 <path>" on ok', async () => {
    (window as any).electronAPI.diagnostic.exportBundle.mockResolvedValue({
      ok: true,
      path: '/home/user/Downloads/sage-diagnostic.zip',
    });

    render(<ExportButton includePrompts={false} includeHostname={false} />);
    fireEvent.click(screen.getByTestId('diagnostic-export-btn'));

    await waitFor(() =>
      expect(screen.getByTestId('diagnostic-message')).toHaveTextContent(
        /已导出到 .*sage-diagnostic\.zip/,
      ),
    );
  });

  it.each([
    ['dialog_cancelled', /已取消/],
    ['backend_unreachable', /无法连接/],
    ['zip_generation_failed', /诊断包生成失败/],
    ['write_failed', /无法写入/],
  ])('shows user-friendly message for code=%s', async (code, regex) => {
    (window as any).electronAPI.diagnostic.exportBundle.mockResolvedValue({
      ok: false,
      code,
      error: 'internal detail',
    });

    render(<ExportButton includePrompts={false} includeHostname={false} />);
    fireEvent.click(screen.getByTestId('diagnostic-export-btn'));

    await waitFor(() => expect(screen.getByTestId('diagnostic-message')).toHaveTextContent(regex));
  });

  it('shows fallback message when electronAPI.diagnostic is undefined (null guard)', async () => {
    // Remove the diagnostic bridge entirely
    (window as any).electronAPI = {};

    render(<ExportButton includePrompts={false} includeHostname={false} />);
    fireEvent.click(screen.getByTestId('diagnostic-export-btn'));

    await waitFor(() =>
      expect(screen.getByTestId('diagnostic-message')).toHaveTextContent(/诊断接口不可用/),
    );
  });

  it('shows catch-block message when exportBundle throws', async () => {
    (window as any).electronAPI.diagnostic.exportBundle.mockRejectedValue(
      new Error('network timeout'),
    );

    render(<ExportButton includePrompts={false} includeHostname={false} />);
    fireEvent.click(screen.getByTestId('diagnostic-export-btn'));

    await waitFor(() =>
      expect(screen.getByTestId('diagnostic-message')).toHaveTextContent(
        /导出异常.*network timeout/,
      ),
    );
  });

  it('passes includePrompts and includeHostname to exportBundle', async () => {
    const mock = (window as any).electronAPI.diagnostic.exportBundle.mockResolvedValue({
      ok: true,
      path: '/tmp/x.zip',
    });

    render(<ExportButton includePrompts={true} includeHostname={true} />);
    fireEvent.click(screen.getByTestId('diagnostic-export-btn'));

    await waitFor(() => expect(mock).toHaveBeenCalled());
    expect(mock).toHaveBeenCalledWith({ includePrompts: true, includeHostname: true });
  });
});
