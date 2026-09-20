/**
 * r90: promptApi 单元测试——模板 CRUD / 排序 / 导入导出信封。
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';

const mockInvoke = vi.fn();

vi.mock('../desktopInvoke', () => ({
  invoke: (...args: unknown[]) => mockInvoke(...args),
}));

import { promptApi } from '../promptApi';
import type { PromptTemplate, PromptTemplateEnvelope } from '../promptApi';

const TPL: PromptTemplate = {
  id: 'pt-1',
  name: '周报模板',
  description: '',
  content: '写周报：{{内容}}',
  created_at: 1,
  updated_at: 2,
};

beforeEach(() => {
  mockInvoke.mockReset();
});

describe('promptApi', () => {
  it('list() invokes prompts_list and unwraps templates', async () => {
    mockInvoke.mockResolvedValueOnce({ templates: [TPL] });
    const r = await promptApi.list();
    expect(mockInvoke).toHaveBeenCalledWith('prompts_list');
    expect(r).toEqual([TPL]);
  });

  it('list() returns [] when templates missing', async () => {
    mockInvoke.mockResolvedValueOnce({});
    expect(await promptApi.list()).toEqual([]);
  });

  it('create() passes name/content and default description', async () => {
    mockInvoke.mockResolvedValueOnce({ template: TPL });
    const r = await promptApi.create('周报模板', '写周报：{{内容}}');
    expect(mockInvoke).toHaveBeenCalledWith('prompts_create', {
      name: '周报模板',
      content: '写周报：{{内容}}',
      description: '',
    });
    expect(r.id).toBe('pt-1');
  });

  it('create() passes explicit description', async () => {
    mockInvoke.mockResolvedValueOnce({ template: TPL });
    await promptApi.create('n', 'c', 'd');
    expect(mockInvoke).toHaveBeenCalledWith('prompts_create', {
      name: 'n',
      content: 'c',
      description: 'd',
    });
  });

  it('update() passes id and partial patch', async () => {
    mockInvoke.mockResolvedValueOnce({ template: { ...TPL, name: '新名' } });
    const r = await promptApi.update('pt-1', { name: '新名' });
    expect(mockInvoke).toHaveBeenCalledWith('prompts_update', { id: 'pt-1', name: '新名' });
    expect(r.name).toBe('新名');
  });

  it('remove() passes id', async () => {
    mockInvoke.mockResolvedValueOnce(undefined);
    await expect(promptApi.remove('pt-1')).resolves.toBeUndefined();
    expect(mockInvoke).toHaveBeenCalledWith('prompts_delete', { id: 'pt-1' });
  });

  it('reorder() passes orderedIds', async () => {
    mockInvoke.mockResolvedValueOnce(undefined);
    await promptApi.reorder(['b', 'a']);
    expect(mockInvoke).toHaveBeenCalledWith('prompts_reorder', { orderedIds: ['b', 'a'] });
  });

  it('exportTemplates() returns envelope as-is', async () => {
    const envelope: PromptTemplateEnvelope = {
      app: 'sage',
      version: 1,
      exported_at: 100,
      templates: [TPL],
    };
    mockInvoke.mockResolvedValueOnce(envelope);
    const r = await promptApi.exportTemplates();
    expect(mockInvoke).toHaveBeenCalledWith('prompts_export');
    expect(r.templates).toHaveLength(1);
    expect(r.app).toBe('sage');
  });

  it('importTemplates() defaults conflict=skip and wraps envelope', async () => {
    const report = { imported: 2, skipped: 1, failed: 0, conflicts: ['dup'] };
    mockInvoke.mockResolvedValueOnce(report);
    const envelope: PromptTemplateEnvelope = { app: 'sage', version: 1, templates: [TPL] };
    const r = await promptApi.importTemplates(envelope);
    expect(mockInvoke).toHaveBeenCalledWith('prompts_import', {
      payload: { ...envelope, conflict: 'skip' },
    });
    expect(r.imported).toBe(2);
    expect(r.conflicts).toEqual(['dup']);
  });

  it('importTemplates() passes explicit conflict=overwrite', async () => {
    mockInvoke.mockResolvedValueOnce({ imported: 1, skipped: 0, failed: 0 });
    const envelope: PromptTemplateEnvelope = { app: 'sage', version: 1, templates: [TPL] };
    await promptApi.importTemplates(envelope, 'overwrite');
    expect(mockInvoke).toHaveBeenCalledWith('prompts_import', {
      payload: { ...envelope, conflict: 'overwrite' },
    });
  });
});
