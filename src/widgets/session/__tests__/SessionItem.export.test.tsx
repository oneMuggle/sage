/**
 * U18: 侧栏会话 HTML 导出按钮测试
 *
 * 点击导出 → sessionApi.exportHtml → downloadHtmlFile 触发下载;
 * 失败时 alert 展示本地化错误。sessionApi 整体 mock,不打 IPC。
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { downloadHtmlFile, sessionApi } from '../../../shared/api/sessionApi';
import { I18nProvider } from '../../../shared/lib/i18n';
import type { Session } from '../../../shared/lib/store';
import { SessionItem } from '../SessionItem';

vi.mock('../../../shared/api/sessionApi', () => ({
  sessionApi: {
    exportHtml: vi.fn(),
  },
  downloadHtmlFile: vi.fn(),
}));

const baseSession = (overrides: Partial<Session> = {}): Session => ({
  id: 's-export-1',
  title: '待导出会话',
  created_at: 1_750_000_000_000,
  updated_at: 1_750_000_000_000,
  last_message_at: null,
  message_count: 3,
  is_pinned: false,
  ...overrides,
});

const renderWithI18n = (ui: React.ReactElement) =>
  render(<I18nProvider defaultLocale="zh">{ui}</I18nProvider>);

describe('SessionItem — HTML export (U18)', () => {
  it('renders export button with localized label', () => {
    renderWithI18n(
      <SessionItem
        session={baseSession()}
        isActive={false}
        onSelect={vi.fn()}
        onDelete={vi.fn()}
      />,
    );

    const button = screen.getByTestId('export-session');
    expect(button).toHaveAttribute('title', '导出为 HTML');
    expect(button).toHaveAttribute('aria-label', '导出为 HTML');
  });

  it('exports and downloads HTML on click', async () => {
    vi.mocked(sessionApi.exportHtml).mockResolvedValue({
      html: '<!DOCTYPE html><html></html>',
      filename: 'sage-session-s-export-1.html',
      session_id: 's-export-1',
      message_count: 3,
      theme: 'auto',
    });

    renderWithI18n(
      <SessionItem
        session={baseSession()}
        isActive={false}
        onSelect={vi.fn()}
        onDelete={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByTestId('export-session'));

    await waitFor(() => {
      expect(sessionApi.exportHtml).toHaveBeenCalledWith('s-export-1');
    });
    expect(downloadHtmlFile).toHaveBeenCalledWith(
      '<!DOCTYPE html><html></html>',
      'sage-session-s-export-1.html',
    );
  });

  it('does not select the session when export clicked', async () => {
    const onSelect = vi.fn();
    vi.mocked(sessionApi.exportHtml).mockResolvedValue({
      html: '<html></html>',
      filename: 'f.html',
      session_id: 's-export-1',
      message_count: 0,
      theme: 'auto',
    });

    renderWithI18n(
      <SessionItem
        session={baseSession()}
        isActive={false}
        onSelect={onSelect}
        onDelete={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByTestId('export-session'));
    expect(onSelect).not.toHaveBeenCalled();
    // 等待导出微任务落地,避免 setState 逸出 act 范围
    await waitFor(() => {
      expect(downloadHtmlFile).toHaveBeenCalled();
    });
  });

  it('alerts localized error when export fails', async () => {
    vi.mocked(sessionApi.exportHtml).mockRejectedValue(new Error('backend 500'));
    const alertSpy = vi.spyOn(window, 'alert').mockImplementation(() => undefined);

    renderWithI18n(
      <SessionItem
        session={baseSession()}
        isActive={false}
        onSelect={vi.fn()}
        onDelete={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByTestId('export-session'));

    await waitFor(() => {
      expect(alertSpy).toHaveBeenCalledWith('导出失败：backend 500');
    });
    alertSpy.mockRestore();
  });
});
