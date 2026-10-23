import type { CommandRoute } from '../commands';

export const promptRoutes: Record<string, CommandRoute> = {
  // R42: drag-to-sort — template ids in their new order (ReorderIn.ordered_ids must be non-empty).
  prompts_reorder: {
    method: 'PUT',
    path: () => '/api/v1/prompts/templates/reorder',
    body: (a) => ({ ordered_ids: a.orderedIds ?? a.ordered_ids }),
  },

  prompts_list: {
    method: 'GET',
    path: () => '/api/v1/prompts/templates',
  },
  prompts_create: {
    method: 'POST',
    path: () => '/api/v1/prompts/templates',
    body: (a) => ({ name: a.name, content: a.content, description: a.description ?? '' }),
  },
  prompts_update: {
    method: 'PUT',
    path: (a) => `/api/v1/prompts/templates/${encodeURIComponent(String(a.id))}`,
    body: (a) => {
      const body: Record<string, unknown> = {};
      if (a.name != null) body.name = a.name;
      if (a.content != null) body.content = a.content;
      if (a.description != null) body.description = a.description;
      return body;
    },
  },
  prompts_delete: {
    method: 'DELETE',
    path: (a) => `/api/v1/prompts/templates/${encodeURIComponent(String(a.id))}`,
  },
  // R30: 模板导入/导出（导出无 body；导入信封即 body）
  prompts_export: {
    method: 'GET',
    path: () => '/api/v1/prompts/templates/export',
  },
  prompts_import: {
    method: 'POST',
    path: () => '/api/v1/prompts/templates/import',
    body: (a) => a.payload as Record<string, unknown>,
  },
};
