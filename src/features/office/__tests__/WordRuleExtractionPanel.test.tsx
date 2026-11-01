import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { officeApi } from '../../../shared/api/officeApi';
import type { WordRuleExtractionResult, WordRuleSpec } from '../../../shared/api/wordAuditTypes';
import { WordRuleExtractionPanel } from '../WordRuleExtractionPanel';

vi.mock('../../../shared/api/officeApi', () => ({
  officeApi: {
    extractWordRules: vi.fn(),
    saveExtractedRulePack: vi.fn(),
  },
}));

const mockedExtract = vi.mocked(officeApi.extractWordRules);
const mockedSave = vi.mocked(officeApi.saveExtractedRulePack);

const RULE_A: WordRuleSpec = {
  id: 'extracted/page.size',
  title: '页面尺寸',
  category: 'page',
  severity: 'error',
  kind: 'page.size',
  params: { size: 'A4' },
  source: 'spec.docx 第 1 段',
  fixable: true,
  fix_hint: '设为 A4',
};

const RULE_B: WordRuleSpec = {
  id: 'extracted/page.margins',
  title: '页边距',
  category: 'page',
  severity: 'error',
  kind: 'page.margins',
  params: { top_cm: 3.7 },
  source: 'spec.docx 第 1 段',
  fixable: true,
  fix_hint: '设置页边距',
};

const RESULT: WordRuleExtractionResult = {
  ok: true,
  source_path: 'spec.docx',
  file_type: 'spec',
  pack: {
    id: 'journal-spec',
    name: '期刊规范',
    version: '1.0',
    rules: [RULE_A, RULE_B],
  },
  candidates: [
    {
      rule: RULE_A,
      confidence: 0.9,
      source_excerpt: 'A4 纸张',
      conflict_group: null,
    },
    {
      rule: RULE_B,
      confidence: 0.95,
      source_excerpt: '上边距 3.7 厘米',
      conflict_group: 'conflict/page.margins',
    },
  ],
  conflicts: [
    {
      kind: 'page.margins',
      rule_ids: [RULE_B.id],
      message: '同一规则类型抽取到不同取值',
    },
  ],
  warnings: [{ code: 'char_indent_unconverted', message: '未识别正文字号' }],
  summary: { rules: 2, candidates: 2, conflicts: 1, warnings: 1 },
};

afterEach(() => {
  vi.clearAllMocks();
});

describe('WordRuleExtractionPanel', () => {
  it('shows a workspace hint and disables extraction without a workspace', () => {
    render(<WordRuleExtractionPanel workspacePath={null} />);

    expect(screen.getByTestId('word-rule-extract-no-workspace')).toBeInTheDocument();
    expect(screen.getByTestId('word-rule-extract-run')).toBeDisabled();
  });

  it('extracts rules and shows confidence, conflicts and warnings', async () => {
    mockedExtract.mockResolvedValue(RESULT);

    render(<WordRuleExtractionPanel workspacePath="/ws" />);
    fireEvent.change(screen.getByTestId('word-rule-extract-path'), {
      target: { value: 'docs/spec.docx' },
    });
    fireEvent.click(screen.getByTestId('word-rule-extract-run'));

    await waitFor(() =>
      expect(screen.getByTestId('word-rule-extract-summary')).toBeInTheDocument(),
    );
    expect(mockedExtract).toHaveBeenCalledWith({
      workspace_path: '/ws',
      file_path: '/ws/docs/spec.docx',
      file_type: 'spec',
      pack_id: 'extracted-pack',
    });
    expect(screen.getByText('置信度 90%')).toBeInTheDocument();
    expect(screen.getByTestId('word-rule-extract-conflicts')).toBeInTheDocument();
    expect(screen.getByTestId('word-rule-extract-warnings')).toBeInTheDocument();
    expect(screen.getByText('上边距 3.7 厘米')).toBeInTheDocument();
  });

  it('saves only enabled rules after toggling one off', async () => {
    mockedExtract.mockResolvedValue(RESULT);
    mockedSave.mockResolvedValue({
      ok: true,
      workspace_path: '/ws',
      origin: 'workspace',
      pack: { ...RESULT.pack, rules: [RULE_B] },
    });

    render(<WordRuleExtractionPanel workspacePath="/ws" />);
    fireEvent.change(screen.getByTestId('word-rule-extract-path'), {
      target: { value: 'spec.docx' },
    });
    fireEvent.click(screen.getByTestId('word-rule-extract-run'));
    await waitFor(() => expect(screen.getByTestId('word-rule-extract-save')).toBeInTheDocument());

    fireEvent.click(screen.getByTestId('word-rule-extract-enable-0'));
    fireEvent.click(screen.getByTestId('word-rule-extract-save'));

    await waitFor(() =>
      expect(screen.getByTestId('word-rule-extract-save-ok')).toBeInTheDocument(),
    );
    expect(mockedSave).toHaveBeenCalledWith({
      workspace_path: '/ws',
      pack: { ...RESULT.pack, rules: [RULE_B] },
    });
    expect(screen.getByText(/已保存规则包 journal-spec/)).toBeInTheDocument();
  });

  it('passes template file type to the extractor', async () => {
    mockedExtract.mockResolvedValue({ ...RESULT, file_type: 'template' });

    render(<WordRuleExtractionPanel workspacePath="/ws" />);
    fireEvent.change(screen.getByTestId('word-rule-extract-type'), {
      target: { value: 'template' },
    });
    fireEvent.change(screen.getByTestId('word-rule-extract-path'), {
      target: { value: 'template.docx' },
    });
    fireEvent.change(screen.getByTestId('word-rule-extract-pack-id'), {
      target: { value: 'template-pack' },
    });
    fireEvent.click(screen.getByTestId('word-rule-extract-run'));

    await waitFor(() =>
      expect(screen.getByTestId('word-rule-extract-summary')).toBeInTheDocument(),
    );
    expect(mockedExtract).toHaveBeenCalledWith({
      workspace_path: '/ws',
      file_path: '/ws/template.docx',
      file_type: 'template',
      pack_id: 'template-pack',
    });
  });

  it('shows extraction errors', async () => {
    mockedExtract.mockRejectedValue(new Error('backend offline'));

    render(<WordRuleExtractionPanel workspacePath="/ws" />);
    fireEvent.change(screen.getByTestId('word-rule-extract-path'), {
      target: { value: 'spec.docx' },
    });
    fireEvent.click(screen.getByTestId('word-rule-extract-run'));

    await waitFor(() => expect(screen.getByTestId('word-rule-extract-error')).toBeInTheDocument());
    expect(screen.getByText('backend offline')).toBeInTheDocument();
  });
});
