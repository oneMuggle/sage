// src/features/office/rules/__tests__/RulesWorkspace.test.tsx
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { toast } from 'sonner';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { MockInstance } from 'vitest';

import { officeRulesApi } from '../../../../shared/api/officeRulesApi';
import type {
  WireAuditResult,
  WireConflictResult,
  WireImportResult,
  WireRuleGroup,
  WireRulePack,
} from '../../../../shared/api/types';
import { I18nProvider } from '../../../../shared/lib/i18n';
import { downloadPlaybookText } from '../../../playbook/playbookDownload';
import { RulesWorkspace } from '../RulesWorkspace';

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
}));
vi.mock('../../../playbook/playbookDownload', () => ({
  downloadPlaybookText: vi.fn(),
}));
vi.mock('../../../../shared/api/officeRulesApi', () => ({
  officeRulesApi: {
    listGroups: vi.fn(),
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
  },
}));

const mockedApi = {
  listGroups: vi.mocked(officeRulesApi.listGroups),
  createGroup: vi.mocked(officeRulesApi.createGroup),
  deleteGroup: vi.mocked(officeRulesApi.deleteGroup),
  createRule: vi.mocked(officeRulesApi.createRule),
  updateRule: vi.mocked(officeRulesApi.updateRule),
  deleteRule: vi.mocked(officeRulesApi.deleteRule),
  checkConflicts: vi.mocked(officeRulesApi.checkConflicts),
  exportPack: vi.mocked(officeRulesApi.exportPack),
  importPack: vi.mocked(officeRulesApi.importPack),
  audit: vi.mocked(officeRulesApi.audit),
};
const mockedDownload = vi.mocked(downloadPlaybookText);

const GROUP: WireRuleGroup = {
  id: 'group-1',
  name: 'Style',
  description: '',
  rules: [
    {
      id: 'rule-1',
      name: 'No passive voice',
      type: 'format',
      severity: 'warning',
      scope: 'body',
      description: '',
      check_mode: 'regex',
      pattern: '\\bis\\b',
      ai_prompt: null,
      enabled: true,
      group_id: 'group-1',
    },
  ],
  priority: 0,
  builtin: false,
};

function renderWorkspace({
  workspacePath = '/ws',
  filePath = '/ws/spec.docx',
}: { workspacePath?: string; filePath?: string | null } = {}) {
  render(
    <I18nProvider defaultLocale="zh">
      <RulesWorkspace workspacePath={workspacePath} filePath={filePath} />
    </I18nProvider>,
  );
}

describe('RulesWorkspace', () => {
  let confirmSpy: MockInstance<typeof window.confirm>;

  beforeEach(() => {
    Object.values(mockedApi).forEach((mock) => mock.mockReset());
    mockedDownload.mockReset();
    vi.mocked(toast.success).mockReset();
    vi.mocked(toast.error).mockReset();
    vi.mocked(toast.warning).mockReset();
    confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);
    mockedApi.listGroups.mockResolvedValue([GROUP]);
  });

  afterEach(() => {
    confirmSpy.mockRestore();
  });

  it('loads groups on mount and renders the selected group and its rules', async () => {
    renderWorkspace();

    await waitFor(() => expect(screen.getByTestId('rules-group-item-group-1')).toBeInTheDocument());
    expect(screen.getByTestId('rule-detail-name')).toHaveValue('No passive voice');
  });

  it('creating a group calls the API and selects the new group', async () => {
    mockedApi.createGroup.mockResolvedValue({ ...GROUP, id: 'group-new', name: 'New' });
    renderWorkspace();

    await waitFor(() => expect(screen.getByTestId('rules-group-create')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('rules-group-create'));

    fireEvent.change(screen.getByTestId('rules-group-name-input'), { target: { value: 'New' } });
    fireEvent.click(screen.getByTestId('rules-group-create-submit'));

    await waitFor(() =>
      expect(mockedApi.createGroup).toHaveBeenCalledWith({
        name: 'New',
        description: '',
        priority: 0,
      }),
    );
  });

  it('saving the detail form calls updateRule with a wire patch (only changed fields)', async () => {
    mockedApi.updateRule.mockResolvedValue({
      ...GROUP.rules[0],
      description: 'new description',
    });
    renderWorkspace();

    await waitFor(() =>
      expect(screen.getByTestId('rule-detail-name')).toHaveValue('No passive voice'),
    );

    fireEvent.change(screen.getByTestId('rule-detail-description'), {
      target: { value: 'new description' },
    });
    fireEvent.click(screen.getByTestId('rule-detail-save'));

    await waitFor(() =>
      expect(mockedApi.updateRule).toHaveBeenCalledWith('rule-1', {
        description: 'new description',
      }),
    );
  });

  it('deleting a rule calls deleteRule', async () => {
    mockedApi.deleteRule.mockResolvedValue({ deleted: true, id: 'rule-1' });
    renderWorkspace();

    await waitFor(() => expect(screen.getByTestId('rule-detail-name')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('rule-detail-delete'));

    await waitFor(() => expect(mockedApi.deleteRule).toHaveBeenCalledWith('rule-1'));
  });

  it('exporting calls exportPack and downloadPlaybookText', async () => {
    const pack = {
      name: 'Style',
      version: '1.0',
      groups: [GROUP],
      exported_at: '2026-11-07T10:00:00Z',
      exported_by: 'local',
    } as WireRulePack;
    mockedApi.exportPack.mockResolvedValue(pack);
    renderWorkspace();

    await waitFor(() => expect(screen.getByTestId('rules-export')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('rules-export'));

    await waitFor(() =>
      expect(mockedDownload).toHaveBeenCalledWith(
        'Style.sage-rules',
        expect.stringContaining('"exported_at": "2026-11-07T10:00:00Z"'),
        'application/json',
      ),
    );
  });

  it('importing a .sage-rules file reads the text and calls importPack', async () => {
    mockedApi.importPack.mockResolvedValue({
      groups: 1,
      imported_rules: 1,
    } as WireImportResult);
    renderWorkspace();

    const text = JSON.stringify({
      name: 'Style',
      version: '1.0',
      groups: [GROUP],
      exported_at: '2026-11-07T10:00:00Z',
      exported_by: 'local',
    });
    const file = new File([text], 'pack.sage-rules', { type: 'application/json' });
    Object.defineProperty(file, 'text', { value: () => Promise.resolve(text) });

    await waitFor(() => expect(screen.getByTestId('rules-import-input')).toBeInTheDocument());
    fireEvent.change(screen.getByTestId('rules-import-input'), {
      target: { files: [file] },
    });

    await waitFor(() =>
      expect(mockedApi.importPack).toHaveBeenCalledWith(
        expect.objectContaining({ name: 'Style', version: '1.0' }),
      ),
    );
  });

  it('conflicts button opens the dialog when conflicts are returned', async () => {
    mockedApi.checkConflicts.mockResolvedValue({
      conflicts: [
        {
          rule_ids: ['rule-1', 'rule-2'],
          message: 'overlap',
          suggestion: 'keep one',
          severity: 'warning',
        },
      ],
    } as WireConflictResult);
    mockedApi.listGroups.mockResolvedValue([
      {
        ...GROUP,
        rules: [
          ...GROUP.rules,
          {
            ...GROUP.rules[0],
            id: 'rule-2',
            name: 'Other',
            scope: 'body',
            check_mode: 'regex',
          },
        ],
      },
    ]);
    renderWorkspace();

    await waitFor(() => expect(screen.getByTestId('rules-check-conflicts')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('rules-check-conflicts'));

    await waitFor(() => expect(screen.getByTestId('rules-conflict-dialog')).toBeInTheDocument());
    expect(screen.getByTestId('rules-conflict-close')).toBeInTheDocument();
  });

  it('audit button is disabled when filePath is null', async () => {
    renderWorkspace({ workspacePath: '/ws', filePath: null });

    await waitFor(() => expect(screen.getByTestId('rules-audit')).toBeDisabled());
    expect(mockedApi.audit).not.toHaveBeenCalled();
  });

  it('audit renders findings after success', async () => {
    mockedApi.audit.mockResolvedValue({
      findings: [
        {
          rule_id: 'rule-1',
          rule_name: 'No passive voice',
          severity: 'warning',
          message: 'passive voice',
          location: '第 3 段',
          suggestion: 'rewrite',
        },
      ],
      error_count: 0,
      warning_count: 1,
      info_count: 0,
    } as WireAuditResult);
    renderWorkspace();

    await waitFor(() => expect(screen.getByTestId('rules-audit')).not.toBeDisabled());
    fireEvent.click(screen.getByTestId('rules-audit'));

    await waitFor(() =>
      expect(screen.getByTestId('rule-audit-finding-rule-1-0')).toBeInTheDocument(),
    );
  });

  it('selecting a rule in the group list shows it in the detail panel', async () => {
    mockedApi.listGroups.mockResolvedValue([
      {
        ...GROUP,
        rules: [
          ...GROUP.rules,
          {
            ...GROUP.rules[0],
            id: 'rule-2',
            name: 'Second rule',
          },
        ],
      },
    ]);
    renderWorkspace();

    await waitFor(() => expect(screen.getByTestId('rule-item-rule-2')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('rule-item-rule-2'));

    await waitFor(() => expect(screen.getByTestId('rule-detail-name')).toHaveValue('Second rule'));
    expect(screen.getByTestId('rule-item-rule-2')).toHaveAttribute('aria-current', 'true');
  });

  it('creating a rule from the group list opens an empty form and calls createRule', async () => {
    mockedApi.createRule.mockResolvedValue({
      ...GROUP.rules[0],
      id: 'rule-new',
      name: 'Brand new rule',
    });
    renderWorkspace();

    await waitFor(() => expect(screen.getByTestId('rule-create-new')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('rule-create-new'));

    expect(screen.getByTestId('rule-detail-name')).toHaveValue('');

    fireEvent.change(screen.getByTestId('rule-detail-name'), {
      target: { value: 'Brand new rule' },
    });
    fireEvent.change(screen.getByTestId('rule-detail-pattern'), {
      target: { value: '\\bTODO\\b' },
    });
    fireEvent.click(screen.getByTestId('rule-detail-save'));

    await waitFor(() =>
      expect(mockedApi.createRule).toHaveBeenCalledWith(
        'group-1',
        expect.objectContaining({ name: 'Brand new rule' }),
      ),
    );
  });

  it('switching a rule to AI clears the regex pattern', async () => {
    mockedApi.updateRule.mockResolvedValue({ ...GROUP.rules[0], check_mode: 'ai' });
    renderWorkspace();

    await waitFor(() =>
      expect(screen.getByTestId('rule-detail-name')).toHaveValue('No passive voice'),
    );
    fireEvent.change(screen.getByTestId('rule-detail-check-mode'), { target: { value: 'ai' } });
    fireEvent.change(screen.getByTestId('rule-detail-ai-prompt'), {
      target: { value: 'check tone' },
    });
    fireEvent.click(screen.getByTestId('rule-detail-save'));

    await waitFor(() =>
      expect(mockedApi.updateRule).toHaveBeenCalledWith(
        'rule-1',
        expect.objectContaining({ check_mode: 'ai', pattern: '' }),
      ),
    );
  });

  it('toggling enabled calls updateRule with the enabled change', async () => {
    mockedApi.updateRule.mockResolvedValue({ ...GROUP.rules[0], enabled: false });
    renderWorkspace();

    await waitFor(() => expect(screen.getByTestId('rule-detail-enabled')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('rule-detail-enabled'));
    fireEvent.click(screen.getByTestId('rule-detail-save'));

    await waitFor(() =>
      expect(mockedApi.updateRule).toHaveBeenCalledWith('rule-1', { enabled: false }),
    );
  });

  it('deleting the selected rule clears the selection', async () => {
    mockedApi.deleteRule.mockResolvedValue({ deleted: true, id: 'rule-1' });
    mockedApi.listGroups
      .mockResolvedValueOnce([GROUP])
      .mockResolvedValueOnce([{ ...GROUP, rules: [] }]);
    renderWorkspace();

    await waitFor(() => expect(screen.getByTestId('rule-detail-delete')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('rule-detail-delete'));

    await waitFor(() => expect(mockedApi.deleteRule).toHaveBeenCalledWith('rule-1'));
    // After deletion, the detail panel shows an empty form (rule is null, but group still exists)
    expect(screen.getByTestId('rule-detail-name')).toHaveValue('');
  });

  it('shows a load error and retries with a second request', async () => {
    mockedApi.listGroups.mockRejectedValueOnce(new Error('boom')).mockResolvedValue([GROUP]);
    renderWorkspace();

    await waitFor(() => expect(screen.getByTestId('rules-load-error')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('rules-retry'));

    await waitFor(() => expect(screen.getByTestId('rules-group-item-group-1')).toBeInTheDocument());
    expect(mockedApi.listGroups).toHaveBeenCalledTimes(2);
  });

  it('cancel restores all fields so a later save cannot persist the cancelled change', async () => {
    mockedApi.updateRule.mockResolvedValue({ ...GROUP.rules[0], description: 'after cancel' });
    renderWorkspace();

    await waitFor(() => expect(screen.getByTestId('rule-detail-severity')).toHaveValue('warning'));

    fireEvent.change(screen.getByTestId('rule-detail-severity'), { target: { value: 'error' } });
    fireEvent.click(screen.getByTestId('rule-detail-cancel'));
    expect(screen.getByTestId('rule-detail-severity')).toHaveValue('warning');

    fireEvent.change(screen.getByTestId('rule-detail-description'), {
      target: { value: 'after cancel' },
    });
    fireEvent.click(screen.getByTestId('rule-detail-save'));

    await waitFor(() =>
      expect(mockedApi.updateRule).toHaveBeenCalledWith('rule-1', {
        description: 'after cancel',
      }),
    );
    expect(mockedApi.updateRule.mock.calls[0][1]).not.toHaveProperty('severity');
  });

  it('deleting a group confirms first and falls back to another group', async () => {
    const otherGroup: WireRuleGroup = { ...GROUP, id: 'group-2', name: 'Other' };
    mockedApi.deleteGroup.mockResolvedValue({ deleted: true, id: 'group-1' });
    mockedApi.listGroups.mockResolvedValueOnce([GROUP, otherGroup]).mockResolvedValue([otherGroup]);
    renderWorkspace();

    await waitFor(() =>
      expect(screen.getByTestId('rules-group-delete-group-1')).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId('rules-group-delete-group-1'));

    await waitFor(() => expect(mockedApi.deleteGroup).toHaveBeenCalledWith('group-1'));
    await waitFor(() =>
      expect(screen.getByTestId('rules-group-item-group-2')).toHaveAttribute(
        'aria-current',
        'true',
      ),
    );
  });

  it('does not delete a group when confirmation is cancelled', async () => {
    confirmSpy.mockReturnValue(false);
    renderWorkspace();

    await waitFor(() =>
      expect(screen.getByTestId('rules-group-delete-group-1')).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId('rules-group-delete-group-1'));

    expect(confirmSpy).toHaveBeenCalled();
    expect(mockedApi.deleteGroup).not.toHaveBeenCalled();
  });

  it('refuses an oversized rule-pack file without calling importPack', async () => {
    renderWorkspace();

    await waitFor(() => expect(screen.getByTestId('rules-import-input')).toBeInTheDocument());
    const file = new File(['{}'], 'huge.sage-rules', { type: 'application/json' });
    Object.defineProperty(file, 'size', { value: 6 * 1024 * 1024 });
    const text = vi.fn(() => Promise.resolve('{}'));
    Object.defineProperty(file, 'text', { value: text });

    fireEvent.change(screen.getByTestId('rules-import-input'), {
      target: { files: [file] },
    });

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(expect.stringContaining('规则包文件过大')),
    );
    expect(text).not.toHaveBeenCalled();
    expect(mockedApi.importPack).not.toHaveBeenCalled();
  });
});
