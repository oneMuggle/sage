/**
 * r86: projectApi 单元测试——list/register/remove/open/update。
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';

const mockInvoke = vi.fn();

vi.mock('../desktopInvoke', () => ({
  invoke: (...args: unknown[]) => mockInvoke(...args),
}));

vi.mock('./syncAllowedPaths', () => ({
  syncAllowedPathsToMain: vi.fn(),
}));

import { projectApi } from '../projectApi';

const WIRE = {
  id: 'p1', path: 'C:/proj', name: 'proj', created_at: 100, last_opened_at: 200,
  description: 'desc', instructions: null, session_count: 3, last_session_id: 's1',
  allowed_paths: ['C:/proj/src'],
};
// const SUMMARY = {

beforeEach(() => { mockInvoke.mockReset(); });

describe('projectApi', () => {
  it('list() invokes projects_list and maps wire→summary', async () => {
    mockInvoke.mockResolvedValueOnce({ projects: [WIRE] });
    const r = await projectApi.list();
    expect(mockInvoke).toHaveBeenCalledWith('projects_list');
    expect(r[0].id).toBe('p1');
  });

  it('register() passes path and allowed_paths', async () => {
    mockInvoke.mockResolvedValueOnce(WIRE);
    await projectApi.register('C:/proj', ['C:/proj/src']);
    expect(mockInvoke).toHaveBeenCalledWith('projects_register', expect.objectContaining({ path: 'C:/proj' }));
  });

  it('remove() passes id', async () => {
    mockInvoke.mockResolvedValueOnce({ removed: true });
    await projectApi.remove('p1');
    expect(mockInvoke).toHaveBeenCalledWith('projects_remove', expect.objectContaining({ id: 'p1' }));
  });

  it('open() passes id', async () => {
    mockInvoke.mockResolvedValueOnce({ project: WIRE, session: { id: 's1' }, created: false });
    await projectApi.open('p1');
    expect(mockInvoke).toHaveBeenCalledWith('projects_open', expect.objectContaining({ id: 'p1' }));
  });

  it('update() passes id and patch', async () => {
    mockInvoke.mockResolvedValueOnce(WIRE);
    await projectApi.update('p1', { description: 'desc' });
    expect(mockInvoke).toHaveBeenCalledWith('projects_update', expect.objectContaining({ id: 'p1', description: 'desc' }));
  });

  it('propagates invoke errors', async () => {
    mockInvoke.mockRejectedValueOnce(new Error('project not found'));
    await expect(projectApi.list()).rejects.toThrow('project not found');
  });
});
