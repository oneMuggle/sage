import { beforeEach, describe, expect, it, vi } from 'vitest';

// Same mocking scheme as invoke.test.ts: keep node-fetch's named exports real, stub only `fetch`.
vi.mock('node-fetch', async () => {
  const actual = await vi.importActual<typeof import('node-fetch')>('node-fetch');
  return { ...actual, default: vi.fn() };
});

import nodeFetch from 'node-fetch';
import { invokeBackend } from '../invoke';

const mockedFetch = nodeFetch as unknown as ReturnType<typeof vi.fn>;
const BACKEND = 'http://127.0.0.1:8765';
const P = `${BACKEND}/api/v1/projects`;

/** Drive a command through the real invokeBackend and return what would hit the wire. */
async function wire(cmd: string, args: Record<string, unknown>) {
  mockedFetch.mockReset();
  mockedFetch.mockResolvedValueOnce({ ok: true, status: 200, json: async () => ({}) });
  await invokeBackend(cmd, args, BACKEND);
  const [url, init] = mockedFetch.mock.calls[0] as [string, { method: string; body?: string }];
  return {
    url,
    method: init.method,
    body: init.body === undefined ? undefined : JSON.parse(init.body),
  };
}

// Args are what src/shared/api/projectApi.ts passes to invoke(); update/delete carry projectId
// because the backend routes are project-scoped.
describe('project-type IPC commands (never registered before)', () => {
  beforeEach(() => mockedFetch.mockReset());

  it('projects_detect_type posts only the path', async () => {
    expect(await wire('projects_detect_type', { path: 'C:/work/p' })).toEqual({
      url: `${P}/detect-type`,
      method: 'POST',
      body: { path: 'C:/work/p' },
    });
  });

  it('projects_update_type patches project_type on the project', async () => {
    expect(await wire('projects_update_type', { id: 'p1', project_type: 'research' })).toEqual({
      url: `${P}/p1`,
      method: 'PATCH',
      body: { project_type: 'research' },
    });
  });

  it('projects_git_status is a body-less GET', async () => {
    expect(await wire('projects_git_status', { projectId: 'p 1' })).toEqual({
      url: `${P}/p%201/git-status`,
      method: 'GET',
      body: undefined,
    });
  });

  describe('constraints', () => {
    it('list is a GET', async () => {
      const r = await wire('projects_list_constraints', { projectId: 'p1' });
      expect(r).toEqual({ url: `${P}/p1/constraints`, method: 'GET', body: undefined });
    });

    it('create sends only ConstraintCreateRequest fields (no projectId, no stray keys)', async () => {
      const r = await wire('projects_create_constraint', {
        projectId: 'p1',
        category: 'style',
        content: 'no any',
        triggerPattern: '*.ts',
        priority: 8,
        junk: 'x',
      });
      expect(r).toEqual({
        url: `${P}/p1/constraints`,
        method: 'POST',
        body: { category: 'style', content: 'no any', trigger_pattern: '*.ts', priority: 8 },
      });
    });

    it('create omits unset optional fields so backend defaults apply', async () => {
      const r = await wire('projects_create_constraint', {
        projectId: 'p1',
        category: 'c',
        content: 'x',
        triggerPattern: undefined,
      });
      expect(r.body).toEqual({ category: 'c', content: 'x' });
    });

    it('update is project-scoped and sends only the fields that were set', async () => {
      const r = await wire('projects_update_constraint', {
        projectId: 'p1',
        constraintId: 'c1',
        content: 'new',
        enabled: false,
      });
      expect(r).toEqual({
        url: `${P}/p1/constraints/c1`,
        method: 'PATCH',
        body: { content: 'new', enabled: false },
      });
    });

    it('delete is project-scoped', async () => {
      const r = await wire('projects_delete_constraint', { projectId: 'p1', constraintId: 'c 1' });
      expect(r).toEqual({ url: `${P}/p1/constraints/c%201`, method: 'DELETE', body: undefined });
    });

    it("import maps the renderer's category to the backend's template field", async () => {
      const r = await wire('projects_import_constraints', { projectId: 'p1', category: 'coding' });
      expect(r).toEqual({
        url: `${P}/p1/constraints/import-template`,
        method: 'POST',
        body: { template: 'coding' },
      });
    });
  });

  describe('milestones', () => {
    it('list is a GET', async () => {
      const r = await wire('projects_list_milestones', { projectId: 'p1' });
      expect(r).toEqual({ url: `${P}/p1/milestones`, method: 'GET', body: undefined });
    });

    it('create drops `status` (MilestoneCreateRequest has none) and snake_cases the rest', async () => {
      const r = await wire('projects_create_milestone', {
        projectId: 'p1',
        title: 'Beta',
        description: undefined,
        stage: 'build',
        dueDate: '2026-12-01',
        status: 'in_progress',
        sortOrder: 2,
      });
      expect(r).toEqual({
        url: `${P}/p1/milestones`,
        method: 'POST',
        body: { title: 'Beta', stage: 'build', due_date: '2026-12-01', sort_order: 2 },
      });
    });

    it('update is project-scoped, keeps `status`, drops `completedAt`', async () => {
      const r = await wire('projects_update_milestone', {
        projectId: 'p1',
        milestoneId: 'm1',
        status: 'completed',
        sortOrder: 0,
        completedAt: 123,
      });
      expect(r).toEqual({
        url: `${P}/p1/milestones/m1`,
        method: 'PATCH',
        body: { status: 'completed', sort_order: 0 },
      });
    });

    it('delete is project-scoped', async () => {
      const r = await wire('projects_delete_milestone', { projectId: 'p1', milestoneId: 'm1' });
      expect(r).toEqual({ url: `${P}/p1/milestones/m1`, method: 'DELETE', body: undefined });
    });
  });
});
