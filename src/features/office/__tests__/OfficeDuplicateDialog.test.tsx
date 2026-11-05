/**
 * OfficeDuplicateDialog tests — AI workbench Phase 0 (import-side dedup).
 *
 * Coverage:
 *  - nothing renders while `pending` is null (closed state);
 *  - a match renders the staged filename, the existing document card and
 *    the three actions;
 *  - each action reports its choice through `onChoose`;
 *  - more than one duplicate adds the "另有 N 个" hint;
 *  - dismissing the dialog (X button) maps to `keep-copy`, so a batch
 *    paused on a duplicate never loses the user's files.
 */

import { act, fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

// jsdom does not implement ResizeObserver but @headlessui Dialog uses it
// internally; provide a no-op stub so the modal can render.
if (typeof globalThis.ResizeObserver === 'undefined') {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
}

import type { OfficeDocumentSummary } from '../../../shared/api/types';
import { I18nProvider } from '../../../shared/lib/i18n';
import { OfficeDuplicateDialog } from '../OfficeDuplicateDialog';
import type { OfficePendingDuplicate } from '../useOfficeDocuments';

function makeDoc(id: string, overrides: Partial<OfficeDocumentSummary> = {}): OfficeDocumentSummary {
  return {
    id,
    workspace_path: '/tmp/ws',
    doc_type: 'word',
    original_filename: 'report.docx',
    generated_filename: `${id}.docx`,
    status: 'parsed',
    created_at: 1700000000,
    updated_at: 1700000000,
    metadata: { file_size_bytes: 1024 },
    derived_from: null,
    archived_at: null,
    ...overrides,
  };
}

function makePending(overrides: Partial<OfficePendingDuplicate> = {}): OfficePendingDuplicate {
  return {
    filename: 'report.docx',
    duplicates: [makeDoc('doc-1')],
    contentHash: 'sha256:' + 'a'.repeat(64),
    ...overrides,
  };
}

/**
 * Render the dialog and flush Headless UI's enter animation.
 *
 * Transition kicks off its enter transition right after mount and moves
 * state on the next frame/timer tick; leaving that update unflushed
 * produces "not wrapped in act(...)" warnings for every test.
 */
async function renderDialog(pending: OfficePendingDuplicate | null, onChoose = vi.fn()) {
  render(
    <I18nProvider defaultLocale="zh">
      <OfficeDuplicateDialog pending={pending} onChoose={onChoose} />
    </I18nProvider>,
  );
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 50));
  });
  return onChoose;
}

describe('OfficeDuplicateDialog', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders nothing while `pending` is null', async () => {
    await renderDialog(null);
    expect(screen.queryByTestId('office-duplicate-dialog')).toBeNull();
    expect(screen.queryByText('发现重复文件')).toBeNull();
  });

  it('shows the staged filename, the existing document and the three actions', async () => {
    await renderDialog(makePending());

    expect(screen.getByText('发现重复文件')).toBeInTheDocument();
    const body = screen.getByTestId('office-duplicate-dialog');
    expect(body.textContent).toContain('report.docx');
    // Existing document card: label + "WORD · 更新于 …" meta line.
    expect(body.textContent).toContain('已有文档');
    expect(body.textContent).toContain('WORD · 更新于');
    expect(screen.getByRole('button', { name: /打开已有文档/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /作为新版本导入/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /作为副本导入/ })).toBeInTheDocument();
    // Only one duplicate → no "more" hint.
    expect(body.textContent).not.toContain('另有');
  });

  it('reports open-existing when the user chooses to open the existing document', async () => {
    const onChoose = await renderDialog(makePending());
    fireEvent.click(screen.getByRole('button', { name: /打开已有文档/ }));
    expect(onChoose).toHaveBeenCalledTimes(1);
    expect(onChoose).toHaveBeenCalledWith('open-existing');
  });

  it('reports new-version when the user imports it as a new version', async () => {
    const onChoose = await renderDialog(makePending());
    fireEvent.click(screen.getByRole('button', { name: /作为新版本导入/ }));
    expect(onChoose).toHaveBeenCalledWith('new-version');
  });

  it('reports keep-copy when the user imports it as an independent copy', async () => {
    const onChoose = await renderDialog(makePending());
    fireEvent.click(screen.getByRole('button', { name: /作为副本导入/ }));
    expect(onChoose).toHaveBeenCalledWith('keep-copy');
  });

  it('falls back to the generated filename when the existing doc has no original name', async () => {
    await renderDialog(
      makePending({
        duplicates: [makeDoc('doc-2', { original_filename: null, generated_filename: 'old.docx' })],
      }),
    );
    expect(screen.getByTestId('office-duplicate-dialog').textContent).toContain('old.docx');
  });

  it('adds the "另有 N 个" hint when several documents share the bytes', async () => {
    await renderDialog(
      makePending({
        duplicates: [makeDoc('doc-1'), makeDoc('doc-2'), makeDoc('doc-3')],
      }),
    );
    expect(screen.getByTestId('office-duplicate-dialog').textContent).toContain(
      '另有 3 个文档包含相同内容',
    );
  });

  it('dismissing the dialog with Escape maps to keep-copy so the batch keeps its files', async () => {
    const onChoose = await renderDialog(makePending());
    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' });
    expect(onChoose).toHaveBeenCalledWith('keep-copy');
  });
});
