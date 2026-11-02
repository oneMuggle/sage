import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { officeApi } from '../../../shared/api/officeApi';
import type {
  WordBatchAuditResult,
  WordRulePackListResult,
} from '../../../shared/api/wordAuditTypes';
import { WordBatchAuditPanel } from '../WordBatchAuditPanel';

vi.mock('../../../shared/api/officeApi', () => ({
  officeApi: {
    listWordRulePacks: vi.fn(),
    batchAuditWord: vi.fn(),
  },
}));

const mockedList = vi.mocked(officeApi.listWordRulePacks);
const mockedBatch = vi.mocked(officeApi.batchAuditWord);

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

const BATCH: WordBatchAuditResult = {
  ok: false,
  workspace_path: '/ws',
  rule_pack_id: 'general-quality',
  totals: {
    files: 2,
    ok_files: 1,
    failed_files: 1,
    issue_count: 1,
    error_count: 1,
    warning_count: 1,
  },
  files: [
    {
      source_path: '/ws/office/a.docx',
      ok: true,
      issue_count: 1,
      error_count: 1,
      warning_count: 1,
      issues: [
        {
          rule_id: 'page/margins',
          rule_pack_id: 'general-quality',
          category: 'page',
          severity: 'error',
          scope: 'section',
          message: '页边距不符',
        },
        {
          rule_id: 'content/empty_paragraphs',
          rule_pack_id: 'general-quality',
          category: 'content',
          severity: 'warning',
          scope: 'paragraph',
          message: '存在空段落',
        },
      ],
      warnings: [],
    },
    {
      source_path: '/ws/office/b.docx',
      ok: false,
      issue_count: 0,
      error_count: 0,
      warning_count: 0,
      issues: [],
      warnings: [],
      error: '解析失败',
    },
  ],
  report_markdown: '# 批量审校报告\n\n- a.docx: 1 错误 1 警告',
};

const EMPTY: WordBatchAuditResult = {
  ok: true,
  workspace_path: '/ws',
  rule_pack_id: 'general-quality',
  totals: {
    files: 0,
    ok_files: 0,
    failed_files: 0,
    issue_count: 0,
    error_count: 0,
    warning_count: 0,
  },
  files: [],
  report_markdown: null,
};

afterEach(() => {
  vi.clearAllMocks();
});

describe('WordBatchAuditPanel', () => {
  it('runs a batch audit, renders per-file results and toggles the report', async () => {
    mockedList.mockResolvedValue(PACKS);
    mockedBatch.mockResolvedValue(BATCH);

    render(<WordBatchAuditPanel workspacePath="/ws" />);
    await waitFor(() =>
      expect(screen.getByRole('option', { name: /自定义规则/ })).toBeInTheDocument(),
    );

    fireEvent.click(screen.getByTestId('word-batch-run'));

    await waitFor(() => expect(screen.getByTestId('word-batch-summary')).toBeInTheDocument());
    expect(mockedBatch).toHaveBeenCalledWith({
      workspace_path: '/ws',
      pattern: '**/*.docx',
      max_files: 20,
      rulepack_id: 'general-quality',
      include_report: true,
    });
    expect(screen.getByTestId('word-batch-summary')).toHaveTextContent('2 个文件');
    expect(screen.getByTestId('word-batch-file-0')).toHaveTextContent('/ws/office/a.docx');
    expect(screen.getByTestId('word-batch-file-issues-0')).toHaveTextContent('page/margins');
    expect(screen.getByTestId('word-batch-file-1')).toHaveTextContent('解析失败');

    fireEvent.click(screen.getByTestId('word-batch-report-toggle'));
    expect(screen.getByTestId('word-batch-report')).toHaveTextContent('批量审校报告');
    fireEvent.click(screen.getByTestId('word-batch-report-toggle'));
    expect(screen.queryByTestId('word-batch-report')).toBeNull();
  });

  it('passes the chosen pack and clamps the max file count', async () => {
    mockedList.mockResolvedValue(PACKS);
    mockedBatch.mockResolvedValue(BATCH);

    render(<WordBatchAuditPanel workspacePath="/ws" />);
    await waitFor(() =>
      expect(screen.getByRole('option', { name: /自定义规则/ })).toBeInTheDocument(),
    );

    fireEvent.change(screen.getByTestId('word-batch-pack'), { target: { value: 'custom-pack' } });
    fireEvent.change(screen.getByTestId('word-batch-max-files'), { target: { value: '80' } });
    fireEvent.click(screen.getByTestId('word-batch-run'));

    await waitFor(() =>
      expect(mockedBatch).toHaveBeenCalledWith(
        expect.objectContaining({ rulepack_id: 'custom-pack', max_files: 50 }),
      ),
    );
  });

  it('shows an empty state when no files match', async () => {
    mockedList.mockResolvedValue(PACKS);
    mockedBatch.mockResolvedValue(EMPTY);

    render(<WordBatchAuditPanel workspacePath="/ws" />);
    fireEvent.click(screen.getByTestId('word-batch-run'));

    await waitFor(() => expect(screen.getByTestId('word-batch-empty')).toBeInTheDocument());
    expect(screen.queryByTestId('word-batch-report-toggle')).toBeNull();
  });

  it('shows an error message when the batch request fails', async () => {
    mockedList.mockRejectedValue(new Error('no workspace'));
    mockedBatch.mockRejectedValue(new Error('batch failed'));

    render(<WordBatchAuditPanel workspacePath="/ws" />);
    fireEvent.click(screen.getByTestId('word-batch-run'));

    await waitFor(() => expect(screen.getByTestId('word-batch-error')).toBeInTheDocument());
    expect(screen.getByText('batch failed')).toBeInTheDocument();
  });
});
