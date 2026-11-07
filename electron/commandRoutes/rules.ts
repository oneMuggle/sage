/**
 * Rules IPC commands — renderer: src/shared/api/rulesApi.ts;
 * backend: backend/api/rules_routes.py (mounted at /api/v1).
 */
import type { CommandRoute } from '../commands';

const enc = (value: unknown): string => encodeURIComponent(String(value));
const projectId = (a: Record<string, unknown>): string => enc(a.projectId ?? a.project_id);

export const rulesRoutes: Record<string, CommandRoute> = {
  rules_list: {
    method: 'GET',
    path: (a) => `/api/v1/projects/${projectId(a)}/rules`,
  },
  rules_effective: {
    method: 'GET',
    path: (a) => `/api/v1/projects/${projectId(a)}/rules/effective`,
  },
};
