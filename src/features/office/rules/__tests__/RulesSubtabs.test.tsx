// src/features/office/rules/__tests__/RulesSubtabs.test.tsx
//
// Tests for the "extract rules from active document" shortcut that used to
// live inside RulesWorkspace. The shortcut moved up to RulesSubtabs (the
// rules-tab container) so it can act on the already-open document without a
// second file picker.
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { toast } from 'sonner';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { useOfficeWorkspaceStore } from '../../../../entities/office/officeWorkspaceStore';
import { officeRulesApi } from '../../../../shared/api/officeRulesApi';
import type { OfficeDocumentSummary, WireExtractResult } from '../../../../shared/api/types';
import { I18nProvider } from '../../../../shared/lib/i18n';
import { RulesSubtabs } from '../RulesSubtabs';

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
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
  },
}));

const mockedApi = {
  listGroups: vi.mocked(officeRulesApi.listGroups),
  createGroup: vi.mocked(officeRulesApi.createGroup),
  createRule: vi.mocked(officeRulesApi.createRule),
  extractRules: vi.mocked(officeRulesApi.extractRules),
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

function renderSubtabs() {
  render(
    <I18nProvider defaultLocale="zh">
      <RulesSubtabs workspacePath="/ws" onGoToDocuments={() => {}} />
    </I18nProvider>,
  );
}

beforeEach(() => {
  useOfficeWorkspaceStore.setState({ activeDocument: ACTIVE_DOC }, true);
  // `clearAllMocks` would not drop queued `...Once` values or default
  // implementations, so reset each api mock explicitly per test.
  mockedApi.listGroups.mockReset().mockResolvedValue([]);
  mockedApi.createGroup.mockReset();
  mockedApi.createRule.mockReset();
  mockedApi.extractRules.mockReset();
});

afterEach(() => {
  useOfficeWorkspaceStore.setState({ activeDocument: null }, true);
});

describe('RulesSubtabs — extract from active document', () => {
  it('extraction creates a new group with the extracted rules', async () => {
    mockedApi.extractRules.mockResolvedValue({
      rules: [
        {
          id: '',
          name: 'Extracted rule',
          type: 'format',
          severity: 'warning',
          scope: 'body',
          description: '',
          check_mode: 'ai',
          pattern: null,
          ai_prompt: 'check tone',
          enabled: true,
          group_id: '',
        },
      ],
      warnings: [],
    } as WireExtractResult);
    mockedApi.createGroup.mockResolvedValue({
      id: 'group-extract',
      name: 'spec · 抽取规则',
      description: '',
      rules: [],
      priority: 0,
      builtin: false,
    });
    mockedApi.createRule.mockResolvedValue({
      id: 'rule-new',
      name: 'Extracted rule',
      type: 'format',
      severity: 'warning',
      scope: 'body',
      description: '',
      check_mode: 'ai',
      pattern: null,
      ai_prompt: 'check tone',
      enabled: true,
      group_id: 'group-extract',
    });
    // Second listGroups call happens after the extract bumps reloadKey.
    mockedApi.listGroups.mockResolvedValueOnce([]).mockResolvedValue([
      {
        id: 'group-extract',
        name: 'spec · 抽取规则',
        description: '',
        rules: [],
        priority: 0,
        builtin: false,
      },
    ]);
    renderSubtabs();

    await waitFor(() =>
      expect(screen.getByTestId('office-rules-extract-from-doc')).not.toBeDisabled(),
    );
    await act(async () => {
      fireEvent.click(screen.getByTestId('office-rules-extract-from-doc'));
    });

    await waitFor(() =>
      expect(mockedApi.createGroup).toHaveBeenCalledWith(
        expect.objectContaining({ name: 'spec · 抽取规则' }),
      ),
    );
    expect(mockedApi.createRule).toHaveBeenCalledWith(
      'group-extract',
      expect.objectContaining({ check_mode: 'ai', ai_prompt: 'check tone' }),
    );
  });

  it('keeps the partial group visible and reports failure when a rule fails', async () => {
    mockedApi.extractRules.mockResolvedValue({
      rules: [
        {
          id: '',
          name: 'Extracted one',
          type: 'format',
          severity: 'warning',
          scope: 'body',
          description: '',
          check_mode: 'ai',
          pattern: null,
          ai_prompt: 'check one',
          enabled: true,
          group_id: '',
        },
        {
          id: '',
          name: 'Extracted two',
          type: 'format',
          severity: 'warning',
          scope: 'body',
          description: '',
          check_mode: 'ai',
          pattern: null,
          ai_prompt: 'check two',
          enabled: true,
          group_id: '',
        },
      ],
      warnings: [],
    } as WireExtractResult);
    mockedApi.createGroup.mockResolvedValue({
      id: 'group-extract',
      name: 'spec · 抽取规则',
      description: '',
      rules: [],
      priority: 0,
      builtin: false,
    });
    mockedApi.createRule
      .mockResolvedValueOnce({
        id: 'rule-new-1',
        name: 'Extracted one',
        type: 'format',
        severity: 'warning',
        scope: 'body',
        description: '',
        check_mode: 'ai',
        pattern: null,
        ai_prompt: 'check one',
        enabled: true,
        group_id: 'group-extract',
      })
      .mockRejectedValueOnce(new Error('boom'));
    // After bumping reloadKey the workspace refetches groups.
    mockedApi.listGroups.mockResolvedValueOnce([]).mockResolvedValue([
      {
        id: 'group-extract',
        name: 'spec · 抽取规则',
        description: '',
        rules: [],
        priority: 0,
        builtin: false,
      },
    ]);
    renderSubtabs();

    await waitFor(() =>
      expect(screen.getByTestId('office-rules-extract-from-doc')).not.toBeDisabled(),
    );
    await act(async () => {
      fireEvent.click(screen.getByTestId('office-rules-extract-from-doc'));
    });

    // The workspace re-listed groups after the partial failure: once on
    // mount, once more when the parent bumped `reloadKey`.
    await waitFor(() => expect(mockedApi.listGroups).toHaveBeenCalledTimes(2));
    expect(toast.error).toHaveBeenCalledWith(expect.stringContaining('已抽取部分规则'));
  });

  it('is disabled when no document is selected', async () => {
    useOfficeWorkspaceStore.setState({ activeDocument: null }, true);
    renderSubtabs();

    await waitFor(() => expect(screen.getByTestId('office-rules-extract-from-doc')).toBeDisabled());
  });
});
