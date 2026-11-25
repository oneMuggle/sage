// src/features/office/rules/__tests__/RulesSubtabs.test.tsx
//
// Tests for the "extract rules from active document" shortcut in RulesSubtabs.
// The shortcut now opens a draft-review modal (RuleExtractionDraft) instead of
// persisting extracted rules immediately: the user reviews, edits, selects and
// then commits via POST /rules/extract/commit.
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { toast } from 'sonner';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { useOfficeWorkspaceStore } from '../../../../entities/office/officeWorkspaceStore';
import { officeRulesApi } from '../../../../shared/api/officeRulesApi';
import type { OfficeDocumentSummary, WireDraftExtractResult } from '../../../../shared/api/types';
import { I18nProvider } from '../../../../shared/lib/i18n';
import { RulesSubtabs } from '../RulesSubtabs';
import { useRuleDraftStore } from '../ruleDraftStore';

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() },
}));
vi.mock('../../../../shared/api/officeRulesApi', () => ({
  officeRulesApi: {
    listGroups: vi.fn().mockResolvedValue([]),
    createGroup: vi.fn(),
    updateGroup: vi.fn(),
    deleteGroup: vi.fn(),
    createRule: vi.fn(),
    updateRule: vi.fn(),
    deleteRule: vi.fn(),
    checkConflicts: vi.fn(),
    exportPack: vi.fn(),
    importPack: vi.fn(),
    audit: vi.fn(),
    extractRules: vi.fn(),
    extractDraft: vi.fn(),
    commitRules: vi.fn(),
  },
}));

const mockedApi = {
  listGroups: vi.mocked(officeRulesApi.listGroups),
  extractDraft: vi.mocked(officeRulesApi.extractDraft),
  commitRules: vi.mocked(officeRulesApi.commitRules),
};

const ACTIVE_DOC: OfficeDocumentSummary = {
  id: 'doc-1',
  workspace_path: '/ws',
  doc_type: 'word',
  original_filename: 'spec.docx',
  generated_filename: 'generated.docx',
  status: 'parsed',
  created_at: 0,
  updated_at: 0,
  metadata: { file_size_bytes: 0 },
  derived_from: null,
  archived_at: null,
};

function draftRule(overrides: Record<string, unknown> = {}) {
  return {
    temp_id: 'draft_0',
    name: '正文字体',
    kind: 'style.font',
    params: { cjk_font: '宋体', size_pt: 12 },
    category: 'style',
    severity: 'warning',
    confidence: 0.95,
    source_excerpt: '模板统计 156/164 段',
    conflict_group: null,
    suggested_check_mode: 'ai',
    suggested_ai_prompt: '检查正文字体是否为宋体小四',
    suggested_type: 'format',
    suggested_scope: 'body',
    description: '',
    ...overrides,
  };
}

function renderSubtabs() {
  render(
    <I18nProvider defaultLocale="zh">
      <RulesSubtabs workspacePath="/ws" onGoToDocuments={() => {}} />
    </I18nProvider>,
  );
}

beforeEach(() => {
  useOfficeWorkspaceStore.setState({ activeDocument: ACTIVE_DOC }, true);
  useRuleDraftStore.getState().reset();
  mockedApi.listGroups.mockReset().mockResolvedValue([]);
  mockedApi.extractDraft.mockReset();
  mockedApi.commitRules.mockReset();
});

afterEach(() => {
  useOfficeWorkspaceStore.setState({ activeDocument: null }, true);
  useRuleDraftStore.getState().reset();
});

describe('RulesSubtabs — extract from active document (draft review)', () => {
  it('extraction opens the draft panel with the extracted rules', async () => {
    mockedApi.extractDraft.mockResolvedValue({
      rules: [draftRule()],
      conflicts: [],
      warnings: [],
    } as WireDraftExtractResult);
    renderSubtabs();

    await waitFor(() =>
      expect(screen.getByTestId('office-rules-extract-from-doc')).not.toBeDisabled(),
    );
    await act(async () => {
      fireEvent.click(screen.getByTestId('office-rules-extract-from-doc'));
    });

    await waitFor(() => expect(screen.getByTestId('rule-extraction-draft')).toBeInTheDocument());
    expect(screen.getByText('正文字体')).toBeInTheDocument();
    expect(screen.getByText(/95%/)).toBeInTheDocument();
    // Nothing persisted yet — no commit call.
    expect(mockedApi.commitRules).not.toHaveBeenCalled();
  });

  it('committing the draft persists the selected rules', async () => {
    mockedApi.extractDraft.mockResolvedValue({
      rules: [draftRule(), draftRule({ temp_id: 'draft_1', name: '行间距', confidence: 0.42 })],
      conflicts: [],
      warnings: [],
    } as WireDraftExtractResult);
    mockedApi.commitRules.mockResolvedValue({ group_id: 'group-extract', rules_created: 1 });
    mockedApi.listGroups.mockResolvedValue([]);
    renderSubtabs();

    await waitFor(() =>
      expect(screen.getByTestId('office-rules-extract-from-doc')).not.toBeDisabled(),
    );
    await act(async () => {
      fireEvent.click(screen.getByTestId('office-rules-extract-from-doc'));
    });
    await waitFor(() => expect(screen.getByTestId('rule-extraction-draft')).toBeInTheDocument());

    // Low-confidence rule (0.42) starts unselected; the 0.95 rule is selected.
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /确认落盘/ }));
    });

    await waitFor(() => expect(mockedApi.commitRules).toHaveBeenCalledTimes(1));
    const payload = mockedApi.commitRules.mock.calls[0][0];
    expect(payload.group_name).toContain('spec');
    expect(payload.rules).toHaveLength(1);
    expect(payload.rules[0]).toMatchObject({
      name: '正文字体',
      check_mode: 'ai',
      structured_params: { cjk_font: '宋体', size_pt: 12 },
      confidence: 0.95,
      source_excerpt: '模板统计 156/164 段',
    });
    await waitFor(() => expect(screen.queryByTestId('rule-extraction-draft')).toBeNull());
    expect(toast.success).toHaveBeenCalledWith('已创建 1 条规则');
  });

  it('surfaces extraction errors inside the draft panel', async () => {
    mockedApi.extractDraft.mockRejectedValue(new Error('boom'));
    renderSubtabs();

    await waitFor(() =>
      expect(screen.getByTestId('office-rules-extract-from-doc')).not.toBeDisabled(),
    );
    await act(async () => {
      fireEvent.click(screen.getByTestId('office-rules-extract-from-doc'));
    });

    await waitFor(() => expect(screen.getByText(/boom/)).toBeInTheDocument());
  });

  it('is disabled when no document is selected', async () => {
    useOfficeWorkspaceStore.setState({ activeDocument: null }, true);
    renderSubtabs();

    await waitFor(() => expect(screen.getByTestId('office-rules-extract-from-doc')).toBeDisabled());
  });

  it('shows a spinner and disables the button while extracting', async () => {
    let releaseExtract: ((value: WireDraftExtractResult) => void) | undefined;
    mockedApi.extractDraft.mockReturnValue(
      new Promise((resolve) => {
        releaseExtract = resolve;
      }),
    );
    renderSubtabs();

    const button = screen.getByTestId('office-rules-extract-from-doc');
    await waitFor(() => expect(button).not.toBeDisabled());
    expect(screen.queryByTestId('office-rules-extract-spinner')).toBeNull();

    await act(async () => {
      fireEvent.click(button);
    });

    await waitFor(() =>
      expect(screen.getByTestId('office-rules-extract-spinner')).toBeInTheDocument(),
    );
    expect(button).toBeDisabled();

    await act(async () => {
      releaseExtract?.({ rules: [], conflicts: [], warnings: [] });
    });
    await waitFor(() => expect(button).not.toBeDisabled());
    expect(screen.queryByTestId('office-rules-extract-spinner')).toBeNull();
  });
});
