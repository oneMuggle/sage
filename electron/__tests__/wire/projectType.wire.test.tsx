import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('node-fetch', async () => {
  const actual = await vi.importActual<typeof import('node-fetch')>('node-fetch');
  const { wireFetch } = await import('./fetchStub');
  return { ...actual, default: wireFetch };
});

import { ConstraintManager } from '../../../src/features/project-type/ConstraintManager';
import { GitStatusWidget } from '../../../src/features/project-type/GitStatusWidget';
import { MilestoneManager } from '../../../src/features/project-type/MilestoneManager';
import { projectApi } from '../../../src/shared/api';

import { received, releaseBackend, strictBody, useBackend } from './harness';

/**
 * Project type / constraints / milestones went through UI -> bridge -> backend for the first time
 * here: the bridge entries never existed, and the renderer and backend contracts had never met.
 * The fake backend enforces what the real request models enforce (extra="forbid").
 */

const P = '/api/v1/projects/p1';

const constraint = (id: string, category: string, content: string) => ({
  id,
  project_id: 'p1',
  category,
  content,
  trigger_pattern: null,
  priority: 5,
  enabled: true,
  created_at: 1,
  updated_at: 2,
});
const milestone = (id: string, title: string, status = 'pending') => ({
  id,
  project_id: 'p1',
  title,
  description: null,
  stage: null,
  due_date: null,
  completed_at: null,
  status,
  sort_order: 1,
  created_at: 3,
});

beforeEach(() => {
  vi.spyOn(window, 'confirm').mockReturnValue(true);
});
afterEach(() => {
  cleanup();
  releaseBackend();
  vi.restoreAllMocks();
});

describe('ConstraintManager over the real bridge', () => {
  it('lists, imports a template, creates, edits and deletes', async () => {
    let rows = [constraint('c1', 'style', 'no any')];
    useBackend([
      { method: 'GET', path: `${P}/constraints`, reply: () => ({ json: { constraints: rows } }) },
      {
        method: 'POST',
        path: `${P}/constraints/import-template`,
        reply: strictBody(['template'], () => {
          rows = [...rows, constraint('c2', 'imported', 'from the coding template')];
          return { status: 201, json: { constraints: rows } };
        }),
      },
      {
        method: 'POST',
        path: `${P}/constraints`,
        reply: strictBody(['category', 'content', 'trigger_pattern', 'priority'], (b) => {
          const row = constraint('c3', String(b.category), String(b.content));
          rows = [...rows, row];
          return { status: 201, json: row };
        }),
      },
      {
        method: 'PATCH',
        path: /^\/api\/v1\/projects\/p1\/constraints\/([^/]+)$/,
        reply: strictBody(
          ['category', 'content', 'trigger_pattern', 'priority', 'enabled'],
          (b, _req, m) => {
            rows = rows.map((r) => (r.id === m[1] ? { ...r, ...b } : r));
            return { json: rows.find((r) => r.id === m[1]) };
          },
        ),
      },
      {
        method: 'DELETE',
        path: /^\/api\/v1\/projects\/p1\/constraints\/([^/]+)$/,
        reply: (_req, m) => {
          rows = rows.filter((r) => r.id !== m[1]);
          return { json: { removed: true } };
        },
      },
    ]);

    render(<ConstraintManager projectId="p1" projectType="coding" />);
    expect(await screen.findByText('no any')).toBeInTheDocument();

    // import template: the renderer's `category` is the backend's `template`
    fireEvent.click(screen.getByRole('button', { name: /导入模板/ }));
    expect(await screen.findByText('from the coding template')).toBeInTheDocument();
    expect(received('POST', `${P}/constraints/import-template`)[0].body).toEqual({
      template: 'coding',
    });

    // create: no projectId in the body, unset optional fields omitted
    fireEvent.click(screen.getByRole('button', { name: /新建约束/ }));
    fireEvent.change(
      await screen.findByPlaceholderText('例如: code-style, git-commit, writing-format'),
      {
        target: { value: 'git' },
      },
    );
    fireEvent.change(screen.getByPlaceholderText('描述具体的约束规则...'), {
      target: { value: 'conventional commits' },
    });
    fireEvent.click(screen.getByRole('button', { name: '保存' }));
    // the list row, not the dialog's textarea that still holds the typed text
    expect(await screen.findByText('conventional commits', { selector: 'p' })).toBeInTheDocument();
    expect(received('POST', `${P}/constraints`)[0].body).toEqual({
      category: 'git',
      content: 'conventional commits',
      priority: 5,
    });

    // edit: project-scoped PATCH
    fireEvent.click(screen.getByRole('button', { name: '编辑约束：style' }));
    fireEvent.change(await screen.findByDisplayValue('no any'), {
      target: { value: 'no any, no ts-ignore' },
    });
    fireEvent.click(screen.getByRole('button', { name: '保存' }));
    expect(await screen.findByText('no any, no ts-ignore', { selector: 'p' })).toBeInTheDocument();
    expect(received('PATCH', `${P}/constraints/c1`)[0].body).toEqual({
      category: 'style',
      content: 'no any, no ts-ignore',
      priority: 5,
      enabled: true,
    });

    // delete: project-scoped DELETE
    fireEvent.click(screen.getByRole('button', { name: '删除约束：style' }));
    await waitFor(() =>
      expect(screen.queryByText('no any, no ts-ignore', { selector: 'p' })).not.toBeInTheDocument(),
    );
    expect(received('DELETE', `${P}/constraints/c1`)).toHaveLength(1);
  });
});

describe('MilestoneManager over the real bridge', () => {
  it('creates (the form status is not a backend field), changes status and deletes', async () => {
    let rows = [milestone('m1', 'Alpha')];
    useBackend([
      { method: 'GET', path: `${P}/milestones`, reply: () => ({ json: { milestones: rows } }) },
      {
        method: 'POST',
        path: `${P}/milestones`,
        reply: strictBody(['title', 'description', 'stage', 'due_date', 'sort_order'], (b) => {
          const row = { ...milestone('m2', String(b.title)), stage: (b.stage as string) ?? null };
          rows = [...rows, row];
          return { status: 201, json: row };
        }),
      },
      {
        method: 'PATCH',
        path: /^\/api\/v1\/projects\/p1\/milestones\/([^/]+)$/,
        reply: strictBody(
          ['title', 'description', 'stage', 'due_date', 'status', 'sort_order'],
          (b, _req, m) => {
            rows = rows.map((r) => (r.id === m[1] ? { ...r, ...b } : r));
            return { json: rows.find((r) => r.id === m[1]) };
          },
        ),
      },
      {
        method: 'DELETE',
        path: /^\/api\/v1\/projects\/p1\/milestones\/([^/]+)$/,
        reply: (_req, m) => {
          rows = rows.filter((r) => r.id !== m[1]);
          return { json: { removed: true } };
        },
      },
    ]);

    render(<MilestoneManager projectId="p1" />);
    expect(await screen.findByText('Alpha')).toBeInTheDocument();

    // status change: PATCH with only `status`
    fireEvent.click(screen.getByRole('button', { name: '进行中' }));
    await waitFor(() => expect(received('PATCH', `${P}/milestones/m1`)).toHaveLength(1));
    expect(received('PATCH', `${P}/milestones/m1`)[0].body).toEqual({ status: 'in_progress' });

    // create: the form sends `status` too, but MilestoneCreateRequest has no such field (422 if forwarded)
    fireEvent.click(screen.getByRole('button', { name: /新建里程碑/ }));
    fireEvent.change(await screen.findByPlaceholderText('例如: 完成 MVP、发布 v1.0'), {
      target: { value: 'Beta' },
    });
    fireEvent.change(screen.getByPlaceholderText('例如: 开发阶段、测试阶段'), {
      target: { value: 'build' },
    });
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'in_progress' } });
    fireEvent.click(screen.getByRole('button', { name: '保存' }));
    expect(await screen.findByText('Beta')).toBeInTheDocument();
    const created = received('POST', `${P}/milestones`)[0].body as Record<string, unknown>;
    expect(created).toMatchObject({ title: 'Beta', stage: 'build' });
    expect(created).not.toHaveProperty('status');

    // delete: project-scoped DELETE
    fireEvent.click(screen.getByRole('button', { name: '删除里程碑：Alpha' }));
    await waitFor(() => expect(screen.queryByText('Alpha')).not.toBeInTheDocument());
    expect(received('DELETE', `${P}/milestones/m1`)).toHaveLength(1);
  });
});

describe('project type, sessions and git status over the real bridge', () => {
  it('detectType maps the backend response to what the UI renders', async () => {
    useBackend([
      {
        method: 'POST',
        path: '/api/v1/projects/detect-type',
        reply: strictBody(['path'], () => ({
          json: {
            project_type: 'coding',
            confidence: 0.9,
            signals: [{ type: 'package.json exists', weight: 0.5 }],
          },
        })),
      },
    ]);
    expect(await projectApi.detectType('C:/work/p')).toEqual({
      detectedType: 'coding',
      confidence: 0.9,
      signals: ['package.json exists'],
    });
  });

  it('updateProjectType patches project_type on the project', async () => {
    useBackend([
      {
        method: 'PATCH',
        path: P,
        reply: strictBody(['project_type'], (b) => ({
          json: {
            id: 'p1',
            path: 'C:/work/p',
            name: 'p',
            created_at: 1,
            last_opened_at: 2,
            project_type: b.project_type,
          },
        })),
      },
    ]);
    const updated = await projectApi.updateProjectType('p1', 'research');
    expect(updated.id).toBe('p1');
    expect(received('PATCH', P)[0].body).toEqual({ project_type: 'research' });
  });

  it('createSession (sidebar "+") posts to /projects/{id}/sessions and gets a NEW session back', async () => {
    useBackend([
      {
        method: 'POST',
        path: `${P}/sessions`,
        reply: () => ({
          status: 201,
          json: {
            project: { id: 'p1', path: 'C:/work/p', name: 'p', created_at: 1, last_opened_at: 2 },
            session: { id: 's-new', title: 'p' },
            created: true,
          },
        }),
      },
    ]);
    const { session } = await projectApi.createSession('p1');
    expect(session.id).toBe('s-new');
    expect(received('POST', `${P}/sessions`)).toHaveLength(1);
  });

  it('GitStatusWidget reads /projects/{id}/git-status', async () => {
    useBackend([
      {
        method: 'GET',
        path: `${P}/git-status`,
        reply: () => ({
          json: {
            is_repo: true,
            current_branch: 'feature/wire',
            modified_files: [],
            staged_files: [],
            untracked_files: [],
            recent_commits: [],
          },
        }),
      },
    ]);
    render(<GitStatusWidget projectId="p1" />);
    expect(await screen.findByText(/feature\/wire/)).toBeInTheDocument();
  });
});
