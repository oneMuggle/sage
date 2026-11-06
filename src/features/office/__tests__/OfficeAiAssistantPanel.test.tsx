import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { officeApi } from '../../../shared/api/officeApi';
import { officeSpecApi } from '../../../shared/api/officeSpecApi';
import type {
  AiReviewResult,
  AiReviseResult,
  OfficeSpecDocument,
} from '../../../shared/api/officeSpecTypes';
import { OfficeAiAssistantPanel } from '../OfficeAiAssistantPanel';

vi.mock('../../../shared/api/officeApi', () => ({
  officeApi: {
    listSpecs: vi.fn(),
    runAiReview: vi.fn(),
    listAiReviews: vi.fn(),
  },
}));

vi.mock('../../../shared/api/officeSpecApi', () => ({
  officeSpecApi: {
    reviseAiIssues: vi.fn(),
  },
}));

const mockedListSpecs = vi.mocked(officeApi.listSpecs);
const mockedRun = vi.mocked(officeApi.runAiReview);
const mockedHistory = vi.mocked(officeApi.listAiReviews);
const mockedRevise = vi.mocked(officeSpecApi.reviseAiIssues);

const SPEC: OfficeSpecDocument = {
  id: 'spec-a',
  workspace_path: '/ws',
  name: '期刊投稿规范',
  source_file_path: 'docs/spec.docx',
  source_content_hash: null,
  rulepack_id: 'journal-spec',
  is_default: true,
  created_at: 1762300000000,
  updated_at: 1762300000000,
};

const REVIEW: AiReviewResult = {
  ok: true,
  doc_id: 'doc-1',
  file_path: '/ws/docs/draft.docx',
  scope: 'full',
  spec_id: 'spec-a',
  spec_name: '期刊投稿规范',
  summary: {
    rules_checked: 12,
    issue_count: 2,
    error_count: 1,
    warning_count: 1,
    info_count: 0,
    spec_issue_count: 1,
    llm_issue_count: 1,
    duration_ms: 480,
    model: 'claude-sonnet-5',
    prompt_tokens: 1200,
    completion_tokens: 300,
  },
  issues: [
    {
      id: 'issue-spec',
      severity: 'error',
      category: 'layout',
      message: '页边距不符合规范',
      suggestion: '改为上下 2.54cm',
      rationale: '§1.2',
      expected: '2.54cm',
      actual: '2.0cm',
      fixable: true,
      location: { paragraph_index: 0, paragraph_text: '标题' },
      source: {
        kind: 'spec',
        spec_id: 'spec-a',
        spec_name: '期刊投稿规范',
        rule_id: 'margins',
        rule_pack_id: 'journal-spec',
      },
    },
    {
      id: 'issue-llm',
      severity: 'warning',
      category: 'clarity',
      message: '摘要表述可以更凝练',
      suggestion: '压缩第三句',
      rationale: '语义重复',
      expected: null,
      actual: null,
      fixable: false,
      location: null,
      source: {
        kind: 'llm',
        spec_id: null,
        spec_name: null,
        rule_id: null,
        rule_pack_id: null,
      },
    },
  ],
  warnings: [],
};

const REVISE: AiReviseResult = {
  ok: true,
  doc_id: 'doc-1',
  snapshot_path: '/ws/.snapshots/1762300000000-draft.docx',
  source_path: '/ws/docs/draft.docx',
  output_path: '/ws/docs/draft.docx',
  overwritten: true,
  planned: 1,
  applied: 1,
  skipped: 0,
  changes: [
    {
      rule_id: null,
      find: '2.0cm',
      replace: '2.54cm',
      comment: '页边距不符合规范 — [spec:margins]',
      applied: true,
      reason: '',
    },
  ],
  warnings: [],
};

beforeEach(() => {
  mockedListSpecs.mockResolvedValue({
    ok: true,
    workspace_path: '/ws',
    specs: [SPEC],
  });
});

afterEach(() => {
  vi.clearAllMocks();
});

describe('OfficeAiAssistantPanel', () => {
  it('asks for a workspace when none is bound', () => {
    render(<OfficeAiAssistantPanel workspacePath={null} />);
    expect(screen.getByTestId('office-ai-no-workspace')).toBeInTheDocument();
    expect(mockedListSpecs).not.toHaveBeenCalled();
  });

  it('requires a file path before running', async () => {
    render(<OfficeAiAssistantPanel workspacePath="/ws" />);
    await screen.findByTestId('office-ai-run');

    fireEvent.click(screen.getByTestId('office-ai-run'));

    expect(await screen.findByTestId('office-ai-error')).toHaveTextContent(
      '请先选择要审校的 Word 文档',
    );
    expect(mockedRun).not.toHaveBeenCalled();
  });

  it('runs the merged review and shows the summary', async () => {
    mockedRun.mockResolvedValue(REVIEW);
    render(<OfficeAiAssistantPanel workspacePath="/ws" />);

    fireEvent.change(await screen.findByTestId('office-ai-path'), {
      target: { value: 'docs/draft.docx' },
    });
    fireEvent.change(screen.getByTestId('office-ai-doc-id'), {
      target: { value: 'doc-1' },
    });
    fireEvent.click(screen.getByTestId('office-ai-run'));

    await waitFor(() => {
      expect(mockedRun).toHaveBeenCalledWith({
        workspace_path: '/ws',
        file_path: '/ws/docs/draft.docx',
        doc_id: 'doc-1',
        scope: 'full',
        use_llm: true,
      });
    });

    expect(await screen.findByTestId('office-ai-current-spec')).toHaveTextContent('期刊投稿规范');
    expect(screen.getByTestId('office-ai-issue-count')).toHaveTextContent('问题 2 个');
    expect(screen.getByTestId('office-ai-issue-issue-spec')).toBeInTheDocument();
    expect(screen.getByTestId('office-ai-issue-source-issue-spec')).toHaveTextContent(
      '规范书 · 期刊投稿规范',
    );
    expect(screen.getByTestId('office-ai-issue-source-issue-llm')).toHaveTextContent('AI 补充');
  });

  it('passes use_llm=false when AI supplement is disabled', async () => {
    mockedRun.mockResolvedValue(REVIEW);
    render(<OfficeAiAssistantPanel workspacePath="/ws" />);

    fireEvent.change(await screen.findByTestId('office-ai-path'), {
      target: { value: 'docs/draft.docx' },
    });
    fireEvent.click(screen.getByTestId('office-ai-use-llm'));
    fireEvent.click(screen.getByTestId('office-ai-run'));

    await waitFor(() => {
      expect(mockedRun).toHaveBeenCalledWith(expect.objectContaining({ use_llm: false }));
    });
  });

  it('filters issues by source', async () => {
    mockedRun.mockResolvedValue(REVIEW);
    render(<OfficeAiAssistantPanel workspacePath="/ws" />);

    fireEvent.change(await screen.findByTestId('office-ai-path'), {
      target: { value: 'docs/draft.docx' },
    });
    fireEvent.click(screen.getByTestId('office-ai-run'));
    await screen.findByTestId('office-ai-issue-issue-spec');

    fireEvent.click(screen.getByTestId('office-ai-filter-llm'));
    expect(screen.getByTestId('office-ai-issue-issue-llm')).toBeInTheDocument();
    expect(screen.queryByTestId('office-ai-issue-issue-spec')).toBeNull();

    fireEvent.click(screen.getByTestId('office-ai-filter-spec'));
    expect(screen.getByTestId('office-ai-issue-issue-spec')).toBeInTheDocument();
    expect(screen.queryByTestId('office-ai-issue-issue-llm')).toBeNull();
  });

  it('loads review history for the document', async () => {
    mockedHistory.mockResolvedValue({
      ok: true,
      doc_id: 'doc-1',
      runs: [
        {
          id: 7,
          doc_id: 'doc-1',
          spec_id: 'spec-a',
          model: 'claude-sonnet-5',
          scope: 'full',
          issue_count: 2,
          summary: null,
          duration_ms: 480,
          prompt_tokens: 1200,
          completion_tokens: 300,
          created_at: 1762300000000,
        },
      ],
    });
    render(<OfficeAiAssistantPanel workspacePath="/ws" />);

    fireEvent.change(await screen.findByTestId('office-ai-doc-id'), {
      target: { value: 'doc-1' },
    });
    fireEvent.click(screen.getByTestId('office-ai-history-load'));

    await waitFor(() => {
      expect(mockedHistory).toHaveBeenCalledWith('doc-1', {
        workspacePath: '/ws',
        limit: 10,
      });
    });
    expect(await screen.findByTestId('office-ai-history-7')).toHaveTextContent('问题 2 个');
  });

  it('shows an error when history is requested without a doc id', async () => {
    render(<OfficeAiAssistantPanel workspacePath="/ws" />);
    fireEvent.click(await screen.findByTestId('office-ai-history-load'));

    expect(await screen.findByTestId('office-ai-history-error')).toHaveTextContent(
      '请先填写文档 ID',
    );
    expect(mockedHistory).not.toHaveBeenCalled();
  });

  // ── T6: 应用到文档 ──────────────────────────────────────────────

  async function renderReviewResult() {
    mockedRun.mockResolvedValue(REVIEW);
    render(<OfficeAiAssistantPanel workspacePath="/ws" />);

    fireEvent.change(await screen.findByTestId('office-ai-path'), {
      target: { value: 'docs/draft.docx' },
    });
    fireEvent.change(screen.getByTestId('office-ai-doc-id'), {
      target: { value: 'doc-1' },
    });
    fireEvent.click(screen.getByTestId('office-ai-run'));
    await screen.findByTestId('office-ai-issue-issue-spec');
  }

  it('renders per-issue checkboxes and disables non-fixable issues', async () => {
    await renderReviewResult();

    expect(screen.getByTestId('office-ai-issue-checkbox-issue-spec')).toBeEnabled();
    expect(screen.getByTestId('office-ai-issue-checkbox-issue-llm')).toBeDisabled();
  });

  it('shows the apply bar only after selecting issues', async () => {
    await renderReviewResult();

    expect(screen.queryByTestId('office-ai-apply-bar')).toBeNull();

    fireEvent.click(screen.getByTestId('office-ai-issue-checkbox-issue-spec'));
    expect(screen.getByTestId('office-ai-apply-bar')).toBeInTheDocument();
    expect(screen.getByTestId('office-ai-apply-button')).toHaveTextContent(
      '应用到文档（1 个问题）',
    );

    fireEvent.click(screen.getByTestId('office-ai-clear-selection'));
    expect(screen.queryByTestId('office-ai-apply-bar')).toBeNull();
  });

  it('select-all selects only fixable issues', async () => {
    await renderReviewResult();

    fireEvent.click(screen.getByTestId('office-ai-select-all'));
    expect(screen.getByTestId('office-ai-apply-button')).toHaveTextContent(
      '应用到文档（1 个问题）',
    );
    expect(screen.getByTestId('office-ai-issue-checkbox-issue-spec')).toBeChecked();
    expect(screen.getByTestId('office-ai-issue-checkbox-issue-llm')).not.toBeChecked();
  });

  it('opens the confirmation dialog and applies revisions', async () => {
    mockedRevise.mockResolvedValue(REVISE);
    await renderReviewResult();

    fireEvent.click(screen.getByTestId('office-ai-issue-checkbox-issue-spec'));
    fireEvent.click(screen.getByTestId('office-ai-apply-button'));

    expect(screen.getByTestId('office-ai-confirm-dialog')).toBeInTheDocument();
    expect(screen.getByTestId('office-ai-confirm-dialog')).toHaveTextContent('页边距不符合规范');

    fireEvent.click(screen.getByTestId('office-ai-confirm-apply'));

    await waitFor(() => {
      expect(mockedRevise).toHaveBeenCalledWith({
        workspace_path: '/ws',
        file_path: '/ws/docs/draft.docx',
        doc_id: 'doc-1',
        issues: [expect.objectContaining({ id: 'issue-spec' })],
        add_comments: true,
      });
    });

    const result = await screen.findByTestId('office-ai-revise-result');
    expect(result).toHaveTextContent('已应用 1 个修订');
    expect(result).toHaveTextContent('/ws/.snapshots/1762300000000-draft.docx');
    // 应用后选择清空，按钮栏消失
    expect(screen.queryByTestId('office-ai-apply-bar')).toBeNull();
  });

  it('surfaces revise errors', async () => {
    mockedRevise.mockRejectedValue(new Error('boom'));
    await renderReviewResult();

    fireEvent.click(screen.getByTestId('office-ai-issue-checkbox-issue-spec'));
    fireEvent.click(screen.getByTestId('office-ai-apply-button'));
    fireEvent.click(screen.getByTestId('office-ai-confirm-apply'));

    expect(await screen.findByTestId('office-ai-revise-error')).toHaveTextContent('boom');
  });
});
