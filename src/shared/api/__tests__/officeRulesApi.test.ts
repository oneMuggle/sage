import { beforeEach, describe, expect, it, vi } from 'vitest';

import { backendRequest, BackendRequestError } from '../backendRequest';
import { officeRulesApi } from '../officeRulesApi';
import type { WireRule, WireRuleGroup, WireRulePack } from '../types';
import { ApiException } from '../utils';

vi.mock('../backendRequest', async () => {
  const actual = await vi.importActual<typeof import('../backendRequest')>('../backendRequest');
  return { ...actual, backendRequest: vi.fn() };
});

const mockedRequest = vi.mocked(backendRequest);

const RULE: WireRule = {
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
};

const GROUP: WireRuleGroup = {
  id: 'group-1',
  name: 'Style',
  description: '',
  rules: [RULE],
  priority: 0,
  builtin: false,
};

const PACK: WireRulePack = {
  name: 'house-style',
  version: '1.0',
  groups: [GROUP],
  exported_at: '2026-11-07T10:00:00Z',
  exported_by: 'local',
};

describe('officeRulesApi', () => {
  beforeEach(() => {
    mockedRequest.mockReset();
  });

  it('lists groups', async () => {
    mockedRequest.mockResolvedValue([GROUP]);

    await expect(officeRulesApi.listGroups()).resolves.toEqual([GROUP]);
    expect(mockedRequest).toHaveBeenCalledWith({ path: '/api/v1/rules/groups', method: 'GET' });
  });

  it('creates a group', async () => {
    mockedRequest.mockResolvedValue(GROUP);
    const input = { name: 'Style', priority: 0 };

    await officeRulesApi.createGroup(input);

    expect(mockedRequest).toHaveBeenCalledWith({
      path: '/api/v1/rules/groups',
      method: 'POST',
      body: input,
    });
  });

  it('updates and deletes a group', async () => {
    mockedRequest.mockResolvedValue(GROUP);
    await officeRulesApi.updateGroup('group-1', { name: 'Renamed' });
    expect(mockedRequest).toHaveBeenLastCalledWith({
      path: '/api/v1/rules/groups/group-1',
      method: 'PUT',
      body: { name: 'Renamed' },
    });

    mockedRequest.mockReset();
    mockedRequest.mockResolvedValue({ deleted: true, id: 'group-1' });
    await expect(officeRulesApi.deleteGroup('group-1')).resolves.toEqual({
      deleted: true,
      id: 'group-1',
    });
    expect(mockedRequest).toHaveBeenCalledWith({
      path: '/api/v1/rules/groups/group-1',
      method: 'DELETE',
    });
  });

  it('creates, updates and deletes rules', async () => {
    mockedRequest.mockResolvedValue(RULE);
    const input = {
      name: 'No passive voice',
      type: 'format' as const,
      severity: 'warning' as const,
      scope: 'body' as const,
      check_mode: 'regex' as const,
      pattern: '\\bis\\b',
    };

    await officeRulesApi.createRule('group-1', input);
    expect(mockedRequest).toHaveBeenLastCalledWith({
      path: '/api/v1/rules/groups/group-1/rules',
      method: 'POST',
      body: input,
    });

    await officeRulesApi.updateRule('rule-1', { enabled: false });
    expect(mockedRequest).toHaveBeenLastCalledWith({
      path: '/api/v1/rules/rules/rule-1',
      method: 'PUT',
      body: { enabled: false },
    });

    mockedRequest.mockReset();
    mockedRequest.mockResolvedValue({ deleted: true, id: 'rule-1' });
    await officeRulesApi.deleteRule('rule-1');
    expect(mockedRequest).toHaveBeenCalledWith({
      path: '/api/v1/rules/rules/rule-1',
      method: 'DELETE',
    });
  });

  it('extracts rules, checks conflicts, exports and imports packs', async () => {
    mockedRequest.mockResolvedValue({ rules: [RULE], warnings: [] });
    await officeRulesApi.extractRules({ workspace_path: '/ws', file_path: '/ws/spec.docx' });
    expect(mockedRequest).toHaveBeenLastCalledWith({
      path: '/api/v1/rules/extract',
      method: 'POST',
      body: { workspace_path: '/ws', file_path: '/ws/spec.docx' },
    });

    mockedRequest.mockResolvedValue({ conflicts: [] });
    await officeRulesApi.checkConflicts(['rule-1', 'rule-2']);
    expect(mockedRequest).toHaveBeenLastCalledWith({
      path: '/api/v1/rules/check-conflicts',
      method: 'POST',
      body: { rule_ids: ['rule-1', 'rule-2'] },
    });

    mockedRequest.mockResolvedValue(PACK);
    await officeRulesApi.exportPack({ group_ids: ['group-1'], name: 'house-style' });
    expect(mockedRequest).toHaveBeenLastCalledWith({
      path: '/api/v1/rules/export',
      method: 'POST',
      body: { group_ids: ['group-1'], name: 'house-style' },
    });

    mockedRequest.mockResolvedValue({ groups: 1, imported_rules: 1 });
    await officeRulesApi.importPack(PACK);
    expect(mockedRequest).toHaveBeenLastCalledWith({
      path: '/api/v1/rules/import',
      method: 'POST',
      body: PACK,
    });
  });

  it('audits a document', async () => {
    mockedRequest.mockResolvedValue({
      findings: [],
      error_count: 0,
      warning_count: 0,
      info_count: 0,
    });
    const request = { workspace_path: '/ws', file_path: '/ws/a.docx', rule_ids: ['rule-1'] };

    await officeRulesApi.audit(request);

    expect(mockedRequest).toHaveBeenCalledWith({
      path: '/api/v1/rules/audit',
      method: 'POST',
      body: request,
    });
  });

  it('wraps backend failures in ApiException', async () => {
    mockedRequest.mockRejectedValue(new BackendRequestError(404, 'group not found'));

    const call = officeRulesApi.updateGroup('missing', { name: 'x' });

    await expect(call).rejects.toBeInstanceOf(ApiException);
    await expect(call).rejects.toMatchObject({ message: 'group not found' });
  });
});
