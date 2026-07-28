/**
 * OfficeDocumentList — Task 6 RED tests.
 *
 * Coverage (M0 Task 6 brief §Step 1):
 *  4. list action callbacks receive the document ID
 *  Plus M0 Task 6 brief §Step 4: Save As / open / show-folder actions
 *  wired WITHOUT a destructive delete action.
 */

import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

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
