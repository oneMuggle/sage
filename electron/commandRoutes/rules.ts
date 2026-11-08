// electron/commandRoutes/rules.ts
/**
 * Rules IPC commands — renderer: src/shared/api/rulesApi.ts;
 * backend: backend/api/rules_routes.py (mounted at /api/v1).
 */
import type { CommandRoute } from '../commands';

const enc = (value: unknown): string => encodeURIComponent(String(value));
const projectId = (a: Record<string, unknown>): string => enc(a.projectId ?? a.project_id);

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

const CREATE_FIELDS = {
  layer: ['layer'],
  category: ['category'],
  content: ['content'],
  trigger_pattern: ['triggerPattern', 'trigger_pattern'],
  priority: ['priority'],
  enabled: ['enabled'],
} as const;

export const rulesRoutes: Record<string, CommandRoute> = {
  rules_list: {
    method: 'GET',
    path: (a) => `/api/v1/projects/${projectId(a)}/rules`,
  },
  rules_effective: {
    method: 'GET',
    path: (a) => `/api/v1/projects/${projectId(a)}/rules/effective`,
  },
  rules_create: {
    method: 'POST',
    path: (a) => `/api/v1/projects/${projectId(a)}/rules`,
    body: (a) => pick(a, CREATE_FIELDS),
  },
  rules_update: {
    method: 'PATCH',
    path: (a) => `/api/v1/projects/${projectId(a)}/rules`,
    // `patch` 内部的键由 invoke.ts 递归转 snake_case（triggerPattern → trigger_pattern）
    body: (a) => ({
      layer: a.layer,
      rule_id: a.ruleId ?? a.rule_id,
      patch: a.patch ?? {},
      expected_updated_at: a.expectedUpdatedAt ?? a.expected_updated_at ?? null,
    }),
  },
  // DELETE 不能带 body（invokeBackend 只给 POST/PUT/PATCH 传 body）→ 走查询参数
  rules_delete: {
    method: 'DELETE',
    path: (a) => {
      const params = new URLSearchParams();
      params.set('layer', String(a.layer));
      params.set('rule_id', String(a.ruleId ?? a.rule_id));
      return `/api/v1/projects/${projectId(a)}/rules?${params.toString()}`;
    },
  },
  rules_raw: {
    method: 'GET',
    path: (a) => {
      const params = new URLSearchParams();
      params.set('layer', String(a.layer));
      return `/api/v1/projects/${projectId(a)}/rules/raw?${params.toString()}`;
    },
  },
  rules_patch_preview: {
    method: 'POST',
    path: (a) => `/api/v1/projects/${projectId(a)}/rules/patches/preview`,
    body: (a) => ({
      instruction: a.instruction ?? '',
      rule_id: a.ruleId ?? a.rule_id ?? null,
    }),
  },
  rules_patch_apply: {
    method: 'POST',
    path: (a) => `/api/v1/projects/${projectId(a)}/rules/patches/apply`,
    // operations 里的 camelCase 键（opId/ruleId/expectedUpdatedAt）由
    // invoke.ts 递归转 snake_case；before/after 内部键原样透传。
    body: (a) => ({
      instruction: a.instruction ?? '',
      operations: a.operations ?? [],
    }),
  },

  // ===== 导出 / 导入（Task 25）=====
  rules_export_rules: {
    method: 'GET',
    path: (a) => {
      const params = new URLSearchParams();
      if (a.format) params.set('format', String(a.format));
      if (a.includeConstraints !== undefined)
        params.set('include_constraints', String(Boolean(a.includeConstraints)));
      else if (a.include_constraints !== undefined)
        params.set('include_constraints', String(Boolean(a.include_constraints)));
      if (a.includePlaybook !== undefined)
        params.set('include_playbook', String(Boolean(a.includePlaybook)));
      if (a.includeGlobal !== undefined)
        params.set('include_global', String(Boolean(a.includeGlobal)));
      if (a.includeDocs !== undefined) params.set('include_docs', String(Boolean(a.includeDocs)));
      const qs = params.toString();
      return `/api/v1/projects/${projectId(a)}/rules/export${qs ? `?${qs}` : ''}`;
    },
  },
  // rawBody: 用户上传的 envelope 里是规则文档原样（snake_case），
  // 若让 invoke.ts 递归转 camel→snake 会把包内字段一起改写。
  rules_import_preview: {
    method: 'POST',
    path: () => '/api/v1/rules/import/preview',
    body: (a) =>
      pick(a, {
        envelope: ['envelope'],
        project_id: ['projectId', 'project_id'],
      }),
    rawBody: true,
  },
  rules_import_apply: {
    method: 'POST',
    path: () => '/api/v1/rules/import/apply',
    body: (a) =>
      pick(a, {
        envelope: ['envelope'],
        project_id: ['projectId', 'project_id'],
        selected: ['selected'],
        overwrite: ['overwrite'],
      }),
    rawBody: true,
  },
  playbook_library_list: {
    method: 'GET',
    path: (a) => {
      const q = a.q ? `?q=${encodeURIComponent(String(a.q))}` : '';
      return `/api/v1/playbooks/library${q}`;
    },
  },
  playbook_library_update: {
    method: 'PATCH',
    path: (a) => `/api/v1/playbooks/library/${enc(a.libraryId ?? a.library_id)}`,
    body: (a) =>
      pick(a, {
        name: ['name'],
        description: ['description'],
        tags: ['tags'],
      }),
  },
};
