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
};
