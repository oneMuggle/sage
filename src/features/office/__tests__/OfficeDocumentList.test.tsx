/**
 * OfficeDocumentList — Task 6 RED tests.
 *
 * Coverage (M0 Task 6 brief §Step 1):
 *  4. list action callbacks receive the document ID
 *  Plus M0 Task 6 brief §Step 4: Save As / open / show-folder actions
 *  wired WITHOUT a destructive delete action.
 *  Plus round-3 N5: batch selection + 批量归档/批量恢复 with summary
 *  toasts and selection clearing.
 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

const mockToastSuccess = vi.fn();
const mockToastError = vi.fn();
const mockToastLoading = vi.fn((_msg: unknown) => 'toast-1');

vi.mock('sonner', () => ({
  toast: {
    success: (...args: unknown[]) => mockToastSuccess(...args),
    error: (...args: unknown[]) => mockToastError(...args),
    loading: (msg: unknown) => mockToastLoading(msg),
  },
}));

import type { OfficeDocumentSummary } from '../../../shared/api/types';
import { I18nProvider } from '../../../shared/lib/i18n';
import { OfficeDocumentList } from '../OfficeDocumentList';

const sampleDocs: OfficeDocumentSummary[] = [
  {
    id: 'doc-1',
    workspace_path: '/tmp/ws',
    doc_type: 'ppt',
    original_filename: 'deck.pptx',
    generated_filename: 'deck.pptx',
    status: 'parsed',
    created_at: 1700000000,
    updated_at: 1700000000,
    metadata: { file_size_bytes: 1024 },
    derived_from: null,
    archived_at: null,
  },
  {
    id: 'doc-2',
    workspace_path: '/tmp/ws',
    doc_type: 'word',
    original_filename: 'doc.docx',
    generated_filename: 'doc.docx',
    status: 'generated',
    created_at: 1700000100,
    updated_at: 1700000100,
    metadata: { file_size_bytes: 2048 },
    derived_from: null,
    archived_at: null,
  },
];

describe('OfficeDocumentList — gateway action callbacks', () => {
  it('forwards the document ID to the Save As callback', () => {
    const onSaveAs = vi.fn();
    render(
      <I18nProvider defaultLocale="zh">
        <OfficeDocumentList documents={sampleDocs} loading={false} onSaveAs={onSaveAs} />
      </I18nProvider>,
    );
    // Use getAllByRole since each document row exposes its own Save As
    // button — assert on the FIRST row to keep the assertion unambiguous.
    const buttons = screen.getAllByRole('button', { name: /Save As|另存为/i });
    fireEvent.click(buttons[0]);
    expect(onSaveAs).toHaveBeenCalledWith('doc-1');
  });

  it('forwards the document ID to the Open callback', () => {
    const onOpen = vi.fn();
    render(
      <I18nProvider defaultLocale="zh">
        <OfficeDocumentList documents={sampleDocs} loading={false} onOpen={onOpen} />
      </I18nProvider>,
    );
    const buttons = screen.getAllByRole('button', { name: /open|打开/i });
    fireEvent.click(buttons[0]);
    expect(onOpen).toHaveBeenCalledWith('doc-1');
  });

  it('forwards the document ID to the Show In Folder callback', () => {
    const onShowInFolder = vi.fn();
    render(
      <I18nProvider defaultLocale="zh">
        <OfficeDocumentList documents={sampleDocs} loading={false} onShowInFolder={onShowInFolder} />
      </I18nProvider>,
    );
    const buttons = screen.getAllByRole('button', { name: /show.*folder|显示.*文件夹/i });
    fireEvent.click(buttons[0]);
    expect(onShowInFolder).toHaveBeenCalledWith('doc-1');
  });

  it('does NOT expose a destructive permanent-delete action', () => {
    // M0 brief: archive/restore and the user confirmation flow are
    // implemented in M3–M5. The M0 management view must not expose a
    // permanent delete action.
    render(
      <I18nProvider defaultLocale="zh">
        <OfficeDocumentList documents={sampleDocs} loading={false} />
      </I18nProvider>,
    );
    expect(screen.queryByRole('button', { name: /delete|删除/i })).toBeNull();
  });

  it('renders the loading and empty states', () => {
    const { rerender } = render(
      <I18nProvider defaultLocale="zh">
        <OfficeDocumentList documents={[]} loading={true} />
      </I18nProvider>,
    );
    expect(screen.getByText(/加载中/)).toBeInTheDocument();

    rerender(
      <I18nProvider defaultLocale="zh">
        <OfficeDocumentList documents={sampleDocs} loading={false} />
      </I18nProvider>,
    );
    expect(screen.queryByText(/暂无历史文档/)).toBeNull();
  });
});

describe('OfficeDocumentList — batch archive/restore (round-3 N5)', () => {
  const archivedDocs: OfficeDocumentSummary[] = [
    { ...sampleDocs[0], id: 'arc-1', archived_at: 1700001000 },
    { ...sampleDocs[1], id: 'arc-2', archived_at: 1700002000 },
  ];

  it('collects checked archived rows, calls onBatchRestore once with the ids, toasts the summary and clears the selection', async () => {
    const onBatchRestore = vi.fn().mockResolvedValue({
      succeeded: ['arc-1', 'arc-2'],
      failed: [],
    });
    render(
      <I18nProvider defaultLocale="zh">
        <OfficeDocumentList
          documents={archivedDocs}
          loading={false}
          variant="archived"
          onBatchRestore={onBatchRestore}
        />
      </I18nProvider>,
    );

    // Disabled while nothing is selected; no restore checkbox rows missing.
    const restoreBtn = screen.getByTestId('office-batch-restore');
    expect(restoreBtn).toBeDisabled();

    fireEvent.click(screen.getByTestId('office-doc-select-arc-1'));
    fireEvent.click(screen.getByTestId('office-doc-select-arc-2'));
    expect(screen.getByTestId('office-batch-count').textContent).toContain('已选 2 项');

    fireEvent.click(restoreBtn);

    await waitFor(() => {
      expect(onBatchRestore).toHaveBeenCalledTimes(1);
    });
    expect(onBatchRestore).toHaveBeenCalledWith(['arc-1', 'arc-2']);
    // Progress toast transitions 开始… → 完成 N 项 via the same toast id.
    expect(mockToastLoading).toHaveBeenCalledWith('开始批量操作…');
    await waitFor(() => {
      expect(mockToastSuccess).toHaveBeenCalledWith('批量操作完成：2 项', { id: 'toast-1' });
    });
    // Selection cleared after the action.
    await waitFor(() => {
      expect(screen.getByTestId('office-batch-count').textContent).toContain('已选 0 项');
    });
    expect((screen.getByTestId('office-doc-select-arc-1') as HTMLInputElement).checked).toBe(false);
    expect((screen.getByTestId('office-doc-select-arc-2') as HTMLInputElement).checked).toBe(false);
  });

  it('counts failures in the summary toast and still clears the selection', async () => {
    const onBatchRestore = vi.fn().mockResolvedValue({
      succeeded: ['arc-1'],
      failed: ['arc-2'],
    });
    render(
      <I18nProvider defaultLocale="zh">
        <OfficeDocumentList
          documents={archivedDocs}
          loading={false}
          variant="archived"
          onBatchRestore={onBatchRestore}
        />
      </I18nProvider>,
    );

    fireEvent.click(screen.getByTestId('office-doc-select-arc-1'));
    fireEvent.click(screen.getByTestId('office-doc-select-arc-2'));
    fireEvent.click(screen.getByTestId('office-batch-restore'));

    await waitFor(() => {
      expect(mockToastError).toHaveBeenCalledWith('批量操作完成：成功 1 项，失败 1 项', {
        id: 'toast-1',
      });
    });
    await waitFor(() => {
      expect(screen.getByTestId('office-batch-count').textContent).toContain('已选 0 项');
    });
  });

  it('offers 批量归档 in the live view with a select-all shortcut', async () => {
    const onBatchArchive = vi.fn().mockResolvedValue({
      succeeded: ['doc-1', 'doc-2'],
      failed: [],
    });
    render(
      <I18nProvider defaultLocale="zh">
        <OfficeDocumentList documents={sampleDocs} loading={false} onBatchArchive={onBatchArchive} />
      </I18nProvider>,
    );

    // Select-all checks every row in one click.
    fireEvent.click(screen.getByTestId('office-batch-select-all'));
    expect((screen.getByTestId('office-doc-select-doc-1') as HTMLInputElement).checked).toBe(true);
    expect((screen.getByTestId('office-doc-select-doc-2') as HTMLInputElement).checked).toBe(true);

    fireEvent.click(screen.getByTestId('office-batch-archive'));

    await waitFor(() => {
      expect(onBatchArchive).toHaveBeenCalledWith(['doc-1', 'doc-2']);
    });
    await waitFor(() => {
      expect(mockToastSuccess).toHaveBeenCalledWith('批量操作完成：2 项', { id: 'toast-1' });
    });
  });
});
