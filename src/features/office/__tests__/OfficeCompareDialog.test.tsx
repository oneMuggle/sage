import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { OfficeDocumentSummary } from '../../../shared/api/types';
import { I18nProvider } from '../../../shared/lib/i18n';
import { OfficeCompareDialog } from '../OfficeCompareDialog';

const mocks = vi.hoisted(() => ({
  compareDocuments: vi.fn(),
}));

vi.mock('../../../shared/api/officeCompareApi', () => ({
  officeCompareApi: { compareDocuments: mocks.compareDocuments },
}));

function makeDoc(
  id: string,
  filename: string,
  overrides: Partial<OfficeDocumentSummary> = {},
): OfficeDocumentSummary {
  return {
    id,
    doc_type: 'word',
    original_filename: filename,
    generated_filename: filename,
    status: 'parsed',
    created_at: 0,
    updated_at: 0,
    metadata: { file_size_bytes: 1024 },
    derived_from: null,
    archived_at: null,
    ...overrides,
  };
}

const docs = [makeDoc('doc-1', '方案A.docx'), makeDoc('doc-2', '方案B.docx')];

function renderDialog(
  overrides: { documents?: OfficeDocumentSummary[]; workspacePath?: string | null } = {},
) {
  return render(
    <I18nProvider defaultLocale="zh">
      <OfficeCompareDialog
        isOpen
        onClose={() => {}}
        workspacePath={overrides.workspacePath === undefined ? '/ws' : overrides.workspacePath}
        documents={overrides.documents ?? docs}
      />
    </I18nProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('OfficeCompareDialog', () => {
  it('shows the empty hint when fewer than two live documents exist', () => {
    renderDialog({
      documents: [docs[0], makeDoc('doc-3', '归档.docx', { archived_at: 123 })],
    });
    expect(screen.getByText('暂无可对比的文档（至少需要 2 篇）')).toBeInTheDocument();
  });

  it('compares the two picked documents via workspace-relative paths', async () => {
    mocks.compareDocuments.mockResolvedValue({
      ok: true,
      format: 'word',
      left_path: 'office/word/doc-1/方案A.docx',
      right_path: 'office/word/doc-2/方案B.docx',
      summary: { added: 2, removed: 1, unchanged: 10 },
      changes: [],
      report_markdown: '```diff\n-旧行\n+新行\n```',
      warnings: [],
    });
    renderDialog();

    fireEvent.change(screen.getByTestId('office-compare-left'), { target: { value: 'doc-1' } });
    fireEvent.change(screen.getByTestId('office-compare-right'), { target: { value: 'doc-2' } });
    fireEvent.click(screen.getByTestId('office-compare-run'));

    await waitFor(() =>
      expect(mocks.compareDocuments).toHaveBeenCalledWith({
        workspace_path: '/ws',
        left_path: 'office/word/doc-1/方案A.docx',
        right_path: 'office/word/doc-2/方案B.docx',
      }),
    );
    expect(await screen.findByTestId('office-compare-summary')).toHaveTextContent(
      '新增 2 行 · 删除 1 行 · 相同 10 行',
    );
    expect(screen.getByTestId('office-compare-report')).toHaveTextContent('新行');
  });

  it('blocks comparison when both dropdowns point at the same document', () => {
    renderDialog();

    fireEvent.change(screen.getByTestId('office-compare-left'), { target: { value: 'doc-1' } });
    fireEvent.change(screen.getByTestId('office-compare-right'), { target: { value: 'doc-1' } });

    expect(screen.getByTestId('office-compare-same-doc')).toBeInTheDocument();
    expect(screen.getByTestId('office-compare-run')).toBeDisabled();
  });

  it('surfaces backend failures in the dialog', async () => {
    mocks.compareDocuments.mockRejectedValue(new Error('boom'));
    renderDialog();

    fireEvent.change(screen.getByTestId('office-compare-left'), { target: { value: 'doc-1' } });
    fireEvent.change(screen.getByTestId('office-compare-right'), { target: { value: 'doc-2' } });
    fireEvent.click(screen.getByTestId('office-compare-run'));

    expect(await screen.findByTestId('office-compare-error')).toHaveTextContent('对比失败');
    expect(screen.getByTestId('office-compare-error')).toHaveTextContent('boom');
  });
});
