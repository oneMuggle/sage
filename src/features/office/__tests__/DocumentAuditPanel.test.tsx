import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { officeApi } from '../../../shared/api/officeApi';
import type {
  WordAuditFixResult,
  WordAuditResult,
  WordRulePackListResult,
  WordTextAnchor,
} from '../../../shared/api/wordAuditTypes';
import { DocumentAuditPanel } from '../DocumentAuditPanel';
import { defaultFixedName } from '../wordAuditFilename';

vi.mock('../../../shared/api/officeApi', () => ({
  officeApi: {
    listWordRulePacks: vi.fn(),
    auditWord: vi.fn(),
    fixWord: vi.fn(),
  },
}));

const mockedList = vi.mocked(officeApi.listWordRulePacks);
const mockedAudit = vi.mocked(officeApi.auditWord);
const mockedFix = vi.mocked(officeApi.fixWord);

const ANCHOR: WordTextAnchor = {
  part: 'word/document.xml',
  paragraph_index: 2,
  run_index: null,
  char_start: 0,
  char_end: 4,
  text_hash: 'abc123',
  table_index: null,
  row: null,
  col: null,
};

const PACKS: WordRulePackListResult = {
  ok: true,
  workspace_path: '/ws',
  packs: [
    {
      id: 'general-quality',
      name: 'Word 通用质量检查',
      version: '1.0',
      origin: 'builtin',
      rule_count: 5,
    },
    {
      id: 'custom-pack',
      name: '自定义规则',
      version: '1.0',
      origin: 'workspace',
      rule_count: 1,
    },
  ],
  warnings: [],
};

const AUDIT: WordAuditResult = {
  ok: false,
  source_path: 'office/word/id/doc.docx',
  rule_pack_id: 'general-quality',
  rule_pack_name: 'Word 通用质量检查',
  summary: {
    rules_checked: 5,
    issue_count: 2,
    error_count: 1,
    warning_count: 1,
    paragraphs: 10,
    tables: 0,
    sections: 1,
  },
  issues: [
    {
      rule_id: 'style/body_font',
      rule_pack_id: 'general-quality',
      category: 'style',
      severity: 'error',
      scope: 'style',
      message: '字号不符',
      expected: '16pt',
      actual: '11pt',
      fix_hint: '改为 16pt',
      fixable: true,
      source: 'GB/T 9704-2012',
      anchor: ANCHOR,
    },
    {
      rule_id: 'content/empty_paragraphs',
      rule_pack_id: 'general-quality',
      category: 'content',
      severity: 'warning',
      scope: 'paragraph',
      message: '连续 3 个空段落',
      actual: '3 个空段落',
      fix_hint: '删除多余空段落',
      fixable: true,
      anchor: { ...ANCHOR, paragraph_index: 4 },
    },
  ],
  warnings: [],
};

const FIX: WordAuditFixResult = {
  ok: true,
  source_path: 'office/word/id/doc.docx',
  output_path: 'office/word/id/doc-fixed.docx',
  overwritten: false,
  rule_pack_id: 'general-quality',
  actions: [{ rule_id: 'style/body_font', kind: 'style.font', fixed_count: 1, message: '字号' }],
  fixed_count: 1,
  before: AUDIT.summary,
  remaining: {
    ...AUDIT,
    ok: true,
    summary: {
      ...AUDIT.summary,
      issue_count: 1,
      error_count: 0,
      warning_count: 1,
    },
    issues: [AUDIT.issues[1]],
  },
  warnings: [],
};

afterEach(() => {
  vi.clearAllMocks();
});

describe('DocumentAuditPanel', () => {
  it('runs an audit, renders anchored issues and filters by severity', async () => {
    mockedList.mockResolvedValue(PACKS);
    mockedAudit.mockResolvedValue(AUDIT);
    const onLocate = vi.fn();

    render(
      <DocumentAuditPanel
        workspacePath="/ws"
        filePath="/ws/office/word/id/doc.docx"
        filename="doc.docx"
        onLocate={onLocate}
      />,
    );

    await waitFor(() => expect(screen.getByTestId('word-audit-summary')).toBeInTheDocument());
    expect(mockedAudit).toHaveBeenCalledWith({
      workspace_path: '/ws',
      file_path: '/ws/office/word/id/doc.docx',
      rulepack_id: 'general-quality',
    });
    expect(screen.getByText('style/body_font')).toBeInTheDocument();
    expect(screen.getByText('定位 第 3 段')).toBeInTheDocument();

    fireEvent.click(screen.getByTestId('word-audit-issue-0'));
    expect(onLocate).toHaveBeenCalledWith(ANCHOR);

    fireEvent.click(screen.getByTestId('word-audit-filter-warning'));
    expect(screen.queryByText('style/body_font')).toBeNull();
    expect(screen.getByText('content/empty_paragraphs')).toBeInTheDocument();
  });

  it('reruns the audit when the rule pack changes', async () => {
    mockedList.mockResolvedValue(PACKS);
    mockedAudit.mockResolvedValue(AUDIT);

    render(<DocumentAuditPanel workspacePath="/ws" filePath="/ws/doc.docx" />);
    await waitFor(() => expect(screen.getByTestId('word-audit-pack')).toBeInTheDocument());
    await waitFor(() =>
      expect(screen.getByRole('option', { name: /自定义规则/ })).toBeInTheDocument(),
    );

    fireEvent.change(screen.getByTestId('word-audit-pack'), {
      target: { value: 'custom-pack' },
    });

    await waitFor(() =>
      expect(mockedAudit).toHaveBeenLastCalledWith({
        workspace_path: '/ws',
        file_path: '/ws/doc.docx',
        rulepack_id: 'custom-pack',
      }),
    );
  });

  it('fixes into a new file and shows before/after counts', async () => {
    mockedList.mockResolvedValue(PACKS);
    mockedAudit.mockResolvedValue(AUDIT);
    mockedFix.mockResolvedValue(FIX);

    render(<DocumentAuditPanel workspacePath="/ws" filePath="/ws/doc.docx" filename="doc.docx" />);
    await waitFor(() => expect(screen.getByTestId('word-audit-fix')).not.toBeDisabled());

    fireEvent.click(screen.getByTestId('word-audit-fix'));

    await waitFor(() => expect(screen.getByTestId('word-audit-fix-result')).toBeInTheDocument());
    expect(mockedFix).toHaveBeenCalledWith({
      workspace_path: '/ws',
      file_path: '/ws/doc.docx',
      rulepack_id: 'general-quality',
      output_filename: 'doc-fixed.docx',
      overwrite: false,
    });
    expect(screen.getByText(/已应用 1 项修复/)).toBeInTheDocument();
    expect(screen.getByText(/复检：0 错误 · 1 警告/)).toBeInTheDocument();
  });

  it('overwrite fix notifies the parent and reruns the audit', async () => {
    mockedList.mockResolvedValue(PACKS);
    mockedAudit.mockResolvedValue(AUDIT);
    mockedFix.mockResolvedValue({ ...FIX, overwritten: true, output_path: 'doc.docx' });
    const onFixed = vi.fn();

    render(
      <DocumentAuditPanel
        workspacePath="/ws"
        filePath="/ws/doc.docx"
        filename="doc.docx"
        onFixed={onFixed}
      />,
    );
    await waitFor(() => expect(screen.getByTestId('word-audit-fix')).not.toBeDisabled());

    fireEvent.click(screen.getByTestId('word-audit-overwrite'));
    fireEvent.click(screen.getByTestId('word-audit-fix'));

    await waitFor(() => expect(onFixed).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(mockedAudit).toHaveBeenCalledTimes(2));
    expect(mockedFix).toHaveBeenCalledWith({
      workspace_path: '/ws',
      file_path: '/ws/doc.docx',
      rulepack_id: 'general-quality',
      overwrite: true,
    });
  });

  it('shows audit errors without hiding the panel', async () => {
    mockedList.mockResolvedValue(PACKS);
    mockedAudit.mockRejectedValue(new Error('backend offline'));

    render(<DocumentAuditPanel workspacePath="/ws" filePath="/ws/doc.docx" />);

    await waitFor(() => expect(screen.getByTestId('word-audit-error')).toBeInTheDocument());
    expect(screen.getByText('backend offline')).toBeInTheDocument();
  });
});

describe('defaultFixedName', () => {
  it('derives a sibling -fixed.docx name', () => {
    expect(defaultFixedName('report.docx', '/ws/report.docx')).toBe('report-fixed.docx');
    expect(defaultFixedName(undefined, '/ws/office/word/id/paper.docx')).toBe('paper-fixed.docx');
    expect(defaultFixedName('notes.txt', '/ws/notes.txt')).toBe('document-fixed.docx');
  });
});
