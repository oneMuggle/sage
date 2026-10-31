/**
 * Project playbook IPC commands — renderer: src/shared/api/playbookApi.ts;
 * backend: backend/api/playbook_routes.py (mounted at /api/v1).
 */
import type { CommandRoute } from '../commands';

const enc = (value: unknown): string => encodeURIComponent(String(value));
const projectId = (a: Record<string, unknown>): string => enc(a.projectId ?? a.project_id);
const playbookId = (a: Record<string, unknown>): string => enc(a.playbookId ?? a.playbook_id);

function pick(
  a: Record<string, unknown>,
  spec: Record<string, readonly string[]>,
): Record<string, unknown> {
  const body: Record<string, unknown> = {};
  for (const [wire, names] of Object.entries(spec)) {
    const name = names.find((candidate) => a[candidate] !== undefined);
    if (name !== undefined) body[wire] = a[name];
  }
  return body;
}

export const playbookRoutes: Record<string, CommandRoute> = {
  playbooks_builtin_list: {
    method: 'GET',
    path: () => '/api/v1/playbooks/builtin',
  },
  playbooks_builtin_get: {
    method: 'GET',
    path: (a) => `/api/v1/playbooks/builtin/${playbookId(a)}`,
  },
  playbook_get_current: {
    method: 'GET',
    path: (a) => `/api/v1/projects/${projectId(a)}/playbook`,
  },
  playbook_bind: {
    method: 'PUT',
    path: (a) => `/api/v1/projects/${projectId(a)}/playbook`,
    body: (a) =>
      pick(a, {
        playbook_id: ['playbookId', 'playbook_id'],
        spec: ['spec'],
        source: ['source'],
      }),
  },
  playbook_audit: {
    method: 'GET',
    path: (a) => `/api/v1/projects/${projectId(a)}/playbook/audit`,
  },
  playbook_audit_ai: {
    method: 'POST',
    path: (a) => `/api/v1/projects/${projectId(a)}/playbook/audit/ai`,
    body: (a) => ({ use_llm: a.useLlm ?? a.use_llm ?? true }),
  },
  playbook_author_preview: {
    method: 'POST',
    path: (a) => `/api/v1/projects/${projectId(a)}/playbook/author/preview`,
    body: (a) => ({
      answers: a.answers ?? {},
      use_llm: a.useLlm ?? a.use_llm ?? true,
    }),
  },
  playbook_stage_confirm: {
    method: 'POST',
    path: (a) => `/api/v1/projects/${projectId(a)}/playbook/stage/confirm`,
    body: (a) =>
      pick(a, {
        stage_id: ['stageId', 'stage_id'],
      }),
  },
  playbook_actions_apply: {
    method: 'POST',
    path: (a) => `/api/v1/projects/${projectId(a)}/playbook/actions/apply`,
    body: (a) => ({ actions: a.actions ?? [] }),
  },
  playbook_export: {
    method: 'GET',
    path: (a) => {
      const format = String(a.format ?? 'json');
      const includeScaffold = a.includeScaffold ?? a.include_scaffold ?? true;
      return `/api/v1/projects/${projectId(a)}/playbook/export?format=${enc(
        format,
      )}&include_scaffold=${includeScaffold ? 'true' : 'false'}`;
    },
  },
  playbook_wiki_export: {
    method: 'POST',
    path: (a) => `/api/v1/projects/${projectId(a)}/playbook/wiki/export`,
  },
  playbook_state_update: {
    method: 'PATCH',
    path: (a) => `/api/v1/projects/${projectId(a)}/playbook/state`,
    body: (a) =>
      pick(a, {
        waivers: ['waivers'],
        manual_done: ['manualDone', 'manual_done'],
        conditions: ['conditions'],
      }),
  },
  playbook_unbind: {
    method: 'DELETE',
    path: (a) => `/api/v1/projects/${projectId(a)}/playbook`,
  },
  playbook_versions: {
    method: 'GET',
    path: (a) => `/api/v1/projects/${projectId(a)}/playbook/versions`,
  },
  playbook_rules_cleanup: {
    method: 'POST',
    path: (a) => `/api/v1/projects/${projectId(a)}/playbook/rules/cleanup`,
  },
  playbook_import_preview: {
    method: 'POST',
    path: () => '/api/v1/playbooks/import/preview',
    body: (a) =>
      pick(a, {
        envelope: ['envelope'],
        project_id: ['projectId', 'project_id'],
      }),
  },
  playbook_import: {
    method: 'POST',
    path: () => '/api/v1/playbooks/import',
    body: (a) => ({
      envelope: a.envelope,
      project_id: a.projectId ?? a.project_id,
      conflict: a.conflict ?? 'save_as_new',
    }),
  },
};
