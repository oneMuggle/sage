/**
 * OfficeEditPreviewDialog tests — office parity batch 2 (item 2.5).
 *
 * Coverage:
 *  - state machine: compose → previewing → result (ok with diff rows /
 *    rejected with backend error); a thrown transport error toasts and
 *    returns to compose.
 *  - op building: word replace_text, excel set_cells, ppt 1-based slide
 *    number → 0-based index; incomplete compose is rejected locally.
 *  - NO apply button: the backend has no page-level apply-update route,
 *    so the dialog shows the apply-in-chat notice instead.
 *  - buildUpdateOps unit table.
 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { toast } from 'sonner';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mockPreviewUpdate = vi.fn();
vi.mock('../../../shared/api/officeApi', () => ({
  officeApi: {
    previewUpdate: (...args: unknown[]) => mockPreviewUpdate(...args),
  },
}));

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import type { OfficeDocumentSummary } from '../../../shared/api/types';
import { I18nProvider } from '../../../shared/lib/i18n';
import { buildUpdateOps, OfficeEditPreviewDialog } from '../OfficeEditPreviewDialog';

const toastMock = toast as unknown as { error: ReturnType<typeof vi.fn> };

function makeDoc(docType: OfficeDocumentSummary['doc_type']): OfficeDocumentSummary {
  return {
    id: 'doc-1',
    workspace_path: '/tmp/ws',
    doc_type: docType,
    original_filename: null,
    generated_filename: `doc.${docType === 'word' ? 'docx' : docType === 'excel' ? 'xlsx' : 'pptx'}`,
    status: 'parsed',
    created_at: 1700000000,
    updated_at: 1700000000,
    metadata: { file_size_bytes: 2048 },
    derived_from: null,
    archived_at: null,
  };
}

function renderDialog(props: {
  docType: OfficeDocumentSummary['doc_type'];
  sheetNames?: string[];
}) {
  return render(
    <I18nProvider defaultLocale="zh">
      <OfficeEditPreviewDialog
        workspacePath="/tmp/ws"
        doc={makeDoc(props.docType)}
        sheetNames={props.sheetNames}
        onClose={vi.fn()}
      />
    </I18nProvider>,
  );
}

describe('OfficeEditPreviewDialog — state machine', () => {
  beforeEach(() => {
    mockPreviewUpdate.mockReset();
    toastMock.error.mockReset();
  });

  it('word: composes replace_text, previews and renders the diff rows', async () => {
    mockPreviewUpdate.mockResolvedValueOnce({
      ok: true,
      changes: [
        {
          op: 'replace_text',
          target: '大模型',
          before: '上下文 …大模型… 医学',
          after: '上下文 …LLM… 医学',
          summary: null,
        },
      ],
      truncated: false,
      error: null,
    });
    renderDialog({ docType: 'word' });

    fireEvent.change(screen.getByTestId('office-edit-find'), { target: { value: '大模型' } });
    fireEvent.change(screen.getByTestId('office-edit-replace'), { target: { value: 'LLM' } });
    fireEvent.click(screen.getByTestId('office-edit-preview-submit'));

    await waitFor(() => {
      expect(mockPreviewUpdate).toHaveBeenCalledWith({
        workspace_path: '/tmp/ws',
        doc_id: 'doc-1',
        ops: [{ op: 'replace_text', find: '大模型', replace: 'LLM' }],
      });
    });

    // Result phase: diff row with before/after styling hooks.
    expect(await screen.findByTestId('office-edit-result')).toBeInTheDocument();
    expect(screen.getByTestId('office-edit-change')).toBeInTheDocument();
    expect(screen.getByText('大模型')).toBeInTheDocument();
    expect(screen.getByText('上下文 …LLM… 医学')).toBeInTheDocument();
    // Dialog reports its phase for e2e hooks.
    expect(screen.getByTestId('office-edit-preview-dialog').dataset.phase).toBe('result');
  });

  it('excel: composes set_cells with the selected sheet', async () => {
    mockPreviewUpdate.mockResolvedValueOnce({
      ok: true,
      changes: [{ op: 'set_cells', target: 'Sheet2!B2', before: '9', after: '10' }],
      truncated: false,
      error: null,
    });
    renderDialog({ docType: 'excel', sheetNames: ['Sheet1', 'Sheet2'] });

    fireEvent.change(screen.getByTestId('office-edit-sheet'), { target: { value: 'Sheet2' } });
    fireEvent.change(screen.getByTestId('office-edit-cell'), { target: { value: 'B2' } });
    fireEvent.change(screen.getByTestId('office-edit-value'), { target: { value: '10' } });
    fireEvent.click(screen.getByTestId('office-edit-preview-submit'));

    await waitFor(() => {
      expect(mockPreviewUpdate).toHaveBeenCalledWith({
        workspace_path: '/tmp/ws',
        doc_id: 'doc-1',
        ops: [{ op: 'set_cells', sheet: 'Sheet2', cells: [{ addr: 'B2', value: '10' }] }],
      });
    });
    expect(await screen.findByTestId('office-edit-result')).toBeInTheDocument();
  });

  it('ppt: converts the 1-based slide number to a 0-based index', async () => {
    mockPreviewUpdate.mockResolvedValueOnce({
      ok: true,
      changes: [{ op: 'set_slide_title', target: 'slide[2]', after: '新标题' }],
      truncated: false,
      error: null,
    });
    renderDialog({ docType: 'ppt' });

    fireEvent.change(screen.getByTestId('office-edit-slide-number'), { target: { value: '3' } });
    fireEvent.change(screen.getByTestId('office-edit-slide-title'), { target: { value: '新标题' } });
    fireEvent.click(screen.getByTestId('office-edit-preview-submit'));

    await waitFor(() => {
      expect(mockPreviewUpdate).toHaveBeenCalledWith({
        workspace_path: '/tmp/ws',
        doc_id: 'doc-1',
        ops: [{ op: 'set_slide_title', index: 2, title: '新标题' }],
      });
    });
    expect(await screen.findByTestId('office-edit-result')).toBeInTheDocument();
  });

  it('rejects an incomplete compose locally without calling the API', async () => {
    renderDialog({ docType: 'word' });
    // No find text filled in.
    fireEvent.click(screen.getByTestId('office-edit-preview-submit'));
    await waitFor(() => {
      expect(toastMock.error).toHaveBeenCalledWith('请完整填写编辑内容');
    });
    expect(mockPreviewUpdate).not.toHaveBeenCalled();
    // Still in compose.
    expect(screen.getByTestId('office-edit-preview-dialog').dataset.phase).toBe('compose');
  });

  it('shows the rejected state with the backend error when ok=false', async () => {
    mockPreviewUpdate.mockResolvedValueOnce({
      ok: false,
      changes: [],
      truncated: false,
      error: 'find text not found: 不存在的词',
    });
    renderDialog({ docType: 'word' });
    fireEvent.change(screen.getByTestId('office-edit-find'), { target: { value: '不存在的词' } });
    fireEvent.click(screen.getByTestId('office-edit-preview-submit'));

    expect(await screen.findByTestId('office-edit-rejected')).toBeInTheDocument();
    expect(screen.getByText(/find text not found/)).toBeInTheDocument();
    expect(screen.queryByTestId('office-edit-change')).toBeNull();
  });

  it('shows the truncated note when the change list was capped', async () => {
    mockPreviewUpdate.mockResolvedValueOnce({
      ok: true,
      changes: [{ op: 'set_cells', target: 'Sheet1!A1', after: 'x' }],
      truncated: true,
      error: null,
    });
    renderDialog({ docType: 'excel', sheetNames: ['Sheet1'] });
    fireEvent.change(screen.getByTestId('office-edit-cell'), { target: { value: 'A1' } });
    fireEvent.change(screen.getByTestId('office-edit-value'), { target: { value: 'x' } });
    fireEvent.click(screen.getByTestId('office-edit-preview-submit'));

    expect(await screen.findByTestId('office-edit-result')).toBeInTheDocument();
    expect(screen.getByText(/仅显示前 200 条/)).toBeInTheDocument();
  });

  it('shows the no-changes note when ok=true but nothing changed', async () => {
    mockPreviewUpdate.mockResolvedValueOnce({ ok: true, changes: [], truncated: false, error: null });
    renderDialog({ docType: 'ppt' });
    fireEvent.change(screen.getByTestId('office-edit-slide-title'), { target: { value: '标题' } });
    fireEvent.click(screen.getByTestId('office-edit-preview-submit'));

    expect(await screen.findByText('没有产生变更')).toBeInTheDocument();
  });

  it('toasts transport errors and returns to compose', async () => {
    mockPreviewUpdate.mockRejectedValueOnce(new Error('backend down'));
    renderDialog({ docType: 'word' });
    fireEvent.change(screen.getByTestId('office-edit-find'), { target: { value: 'x' } });
    fireEvent.click(screen.getByTestId('office-edit-preview-submit'));

    await waitFor(() => {
      expect(toastMock.error).toHaveBeenCalledWith('预览失败: backend down');
    });
    expect(screen.getByTestId('office-edit-preview-dialog').dataset.phase).toBe('compose');
  });
});

describe('OfficeEditPreviewDialog — apply semantics (no apply route)', () => {
  beforeEach(() => {
    mockPreviewUpdate.mockReset();
    toastMock.error.mockReset();
  });

  it('never renders an apply button; the apply-in-chat notice is shown instead', async () => {
    mockPreviewUpdate.mockResolvedValueOnce({
      ok: true,
      changes: [{ op: 'replace_text', before: 'a', after: 'b' }],
      truncated: false,
      error: null,
    });
    renderDialog({ docType: 'word' });
    fireEvent.change(screen.getByTestId('office-edit-find'), { target: { value: 'a' } });
    fireEvent.click(screen.getByTestId('office-edit-preview-submit'));

    expect(await screen.findByTestId('office-edit-result')).toBeInTheDocument();
    // The backend exposes no page-level apply-update HTTP route, so the
    // dialog must not offer an apply action in ANY language.
    expect(screen.queryByRole('button', { name: /应用|apply/i })).toBeNull();
    expect(screen.getByTestId('office-edit-apply-notice')).toHaveTextContent(
      '页面内仅支持预览：应用编辑请在对话中让助手执行相同的 office_update 操作',
    );
  });
});

describe('buildUpdateOps — op composition table', () => {
  type ComposeStateInput = {
    find: string;
    replace: string;
    sheet: string;
    cell: string;
    value: string;
    slideNumber: string;
    slideTitle: string;
  };

  const base: ComposeStateInput = {
    find: '',
    replace: '',
    sheet: '',
    cell: '',
    value: '',
    slideNumber: '1',
    slideTitle: '',
  };

  it('word: requires find; empty replace means delete', () => {
    expect(buildUpdateOps('word', base)).toBeNull();
    expect(buildUpdateOps('word', { ...base, find: ' x ', replace: '' })).toEqual([
      { op: 'replace_text', find: 'x', replace: '' },
    ]);
  });

  it('excel: requires sheet, addr and value', () => {
    expect(buildUpdateOps('excel', { ...base, sheet: 'S' })).toBeNull();
    expect(
      buildUpdateOps('excel', { ...base, sheet: 'S', cell: 'B2', value: ' v ' }),
    ).toEqual([{ op: 'set_cells', sheet: 'S', cells: [{ addr: 'B2', value: 'v' }] }]);
  });

  it('ppt: 1-based number → 0-based index; rejects 0 and non-integers', () => {
    expect(buildUpdateOps('ppt', { ...base, slideNumber: '0', slideTitle: 't' })).toBeNull();
    expect(buildUpdateOps('ppt', { ...base, slideNumber: 'abc', slideTitle: 't' })).toBeNull();
    expect(buildUpdateOps('ppt', { ...base, slideNumber: '2', slideTitle: ' t ' })).toEqual([
      { op: 'set_slide_title', index: 1, title: 't' },
    ]);
  });

  it('pdf is not editable via this dialog', () => {
    expect(buildUpdateOps('pdf', { ...base, find: 'x' })).toBeNull();
  });
});
