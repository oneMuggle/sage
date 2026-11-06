/**
 * P5 (2026-11-05): projectApi 文件引用方法单测 — list/create/delete/scan。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mockInvoke = vi.fn();

vi.mock('../desktopInvoke', () => ({
  invoke: (...args: unknown[]) => mockInvoke(...args),
}));

vi.mock('./syncAllowedPaths', () => ({
  syncAllowedPathsToMain: vi.fn(),
}));

import { projectApi } from '../projectApi';

const REF_WIRE = {
  id: 'ref-1',
  project_id: 'p1',
  alias_name: 'cases',
  rel_path: 'data/cases',
  target_path: '/home/user/external/cases',
  kind: 'directory',
  created_at: 1700000000000,
};

beforeEach(() => {
  mockInvoke.mockReset();
});

describe('projectApi file references (P5)', () => {
  it('listReferences() calls projects_list_references and maps wire→camelCase', async () => {
    mockInvoke.mockResolvedValueOnce({ references: [REF_WIRE] });

    const list = await projectApi.listReferences('p1');

    expect(mockInvoke).toHaveBeenCalledWith('projects_list_references', { id: 'p1' });
    expect(list).toEqual([
      {
        id: 'ref-1',
        projectId: 'p1',
        aliasName: 'cases',
        relPath: 'data/cases',
        targetPath: '/home/user/external/cases',
        kind: 'directory',
        createdAt: 1700000000000,
      },
    ]);
  });

  it('listReferences() tolerates a missing references array', async () => {
    mockInvoke.mockResolvedValueOnce({});
    const list = await projectApi.listReferences('p1');
    expect(list).toEqual([]);
  });

  it('createReference() forwards camelCase args and maps the created reference', async () => {
    mockInvoke.mockResolvedValueOnce(REF_WIRE);

    const created = await projectApi.createReference('p1', {
      relPath: 'data/cases',
      targetPath: '/home/user/external/cases',
      kind: 'directory',
      aliasName: 'cases',
    });

    expect(mockInvoke).toHaveBeenCalledWith('projects_create_reference', {
      id: 'p1',
      relPath: 'data/cases',
      targetPath: '/home/user/external/cases',
      kind: 'directory',
      aliasName: 'cases',
    });
    expect(created.projectId).toBe('p1');
    expect(created.relPath).toBe('data/cases');
    expect(created.targetPath).toBe('/home/user/external/cases');
  });

  it('deleteReference() calls projects_delete_reference with id + referenceId', async () => {
    mockInvoke.mockResolvedValueOnce({ removed: true });

    await projectApi.deleteReference('p1', 'ref-1');

    expect(mockInvoke).toHaveBeenCalledWith('projects_delete_reference', {
      id: 'p1',
      referenceId: 'ref-1',
    });
  });

  it('scanProject() calls projects_scan and maps the scan result', async () => {
    mockInvoke.mockResolvedValueOnce({
      project_id: 'p1',
      scanned: true,
      created_project_ids: ['child-1'],
      reference_count: 2,
    });

    const result = await projectApi.scanProject('p1');

    expect(mockInvoke).toHaveBeenCalledWith('projects_scan', { id: 'p1' });
    expect(result).toEqual({
      projectId: 'p1',
      scanned: true,
      createdProjectIds: ['child-1'],
      referenceCount: 2,
    });
  });

  it('scanProject() defaults missing arrays/counters defensively', async () => {
    mockInvoke.mockResolvedValueOnce({ project_id: 'p1', scanned: false });
    const result = await projectApi.scanProject('p1');
    expect(result.createdProjectIds).toEqual([]);
    expect(result.referenceCount).toBe(0);
  });
});
