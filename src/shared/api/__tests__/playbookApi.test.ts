/**
 * 项目规程 API 客户端单测（2026-10-31）：IPC 命令名与参数映射。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mockInvoke = vi.fn();

vi.mock('../desktopInvoke', () => ({
  invoke: (...args: unknown[]) => mockInvoke(...args),
}));

import { playbookApi } from '../playbookApi';

beforeEach(() => {
  mockInvoke.mockReset();
  mockInvoke.mockResolvedValue({});
});

describe('playbookApi', () => {
  it('listBuiltin 返回数组并调用正确命令', async () => {
    mockInvoke.mockResolvedValueOnce({ playbooks: [{ id: 'p1' }] });
    const result = await playbookApi.listBuiltin();
    expect(result).toEqual([{ id: 'p1' }]);
    expect(mockInvoke).toHaveBeenCalledWith('playbooks_builtin_list');
  });

  it('getCurrent 传 projectId', async () => {
    await playbookApi.getCurrent('proj-1');
    expect(mockInvoke).toHaveBeenCalledWith('playbook_get_current', {
      projectId: 'proj-1',
    });
  });

  it('auditAi 传 projectId 与 useLlm', async () => {
    await playbookApi.auditAi('proj-1', false);
    expect(mockInvoke).toHaveBeenCalledWith('playbook_audit_ai', {
      projectId: 'proj-1',
      useLlm: false,
    });
  });

  it('bind 透传 playbookId/spec/source', async () => {
    await playbookApi.bind('proj-1', {
      playbookId: 'cn-research-grant',
      source: 'custom',
    });
    expect(mockInvoke).toHaveBeenCalledWith('playbook_bind', {
      projectId: 'proj-1',
      playbookId: 'cn-research-grant',
      spec: undefined,
      source: 'custom',
    });
  });

  it('confirmStage 传 stageId', async () => {
    await playbookApi.confirmStage('proj-1', 'execution');
    expect(mockInvoke).toHaveBeenCalledWith('playbook_stage_confirm', {
      projectId: 'proj-1',
      stageId: 'execution',
    });
  });

  it('applyActions 透传动作列表', async () => {
    const actions = [{ type: 'create_folder', payload: { path: '01_开题' } }];
    await playbookApi.applyActions('proj-1', actions);
    expect(mockInvoke).toHaveBeenCalledWith('playbook_actions_apply', {
      projectId: 'proj-1',
      actions,
    });
  });

  it('exportPlaybook 传 format 与 includeScaffold', async () => {
    await playbookApi.exportPlaybook('proj-1', 'md', false);
    expect(mockInvoke).toHaveBeenCalledWith('playbook_export', {
      projectId: 'proj-1',
      format: 'md',
      includeScaffold: false,
    });
  });

  it('importPlaybook 默认 conflict=save_as_new', async () => {
    await playbookApi.importPlaybook({ format: 'sage.playbook' }, 'proj-1');
    expect(mockInvoke).toHaveBeenCalledWith('playbook_import', {
      envelope: { format: 'sage.playbook' },
      projectId: 'proj-1',
      conflict: 'save_as_new',
    });
  });

  it('importPreview 可带 projectId', async () => {
    await playbookApi.importPreview({ format: 'sage.playbook' }, 'proj-1');
    expect(mockInvoke).toHaveBeenCalledWith('playbook_import_preview', {
      envelope: { format: 'sage.playbook' },
      projectId: 'proj-1',
    });
  });
});
