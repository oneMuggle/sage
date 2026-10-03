/**
 * Prompt-template IPC commands — renderer: src/shared/api/promptApi.ts; backend:
 * backend/api/prompt_routes.py (router prefix /prompts, mounted under /api/v1).
 *
 * prompts_reorder is one of the 13 commands #857 silently dropped. Drag-to-sort in
 * Settings -> Prompt templates then threw UnknownIpcCommandError, and the tab's catch{} just
 * reloaded the list: the item snapped back with no message.
 */
import type { CommandRoute } from '../commands';

export const promptRoutes: Record<string, CommandRoute> = {
  // R42: drag-to-sort — template ids in their new order (ReorderIn.ordered_ids must be non-empty).
  prompts_reorder: {
    method: 'PUT',
    path: () => '/api/v1/prompts/templates/reorder',
    body: (a) => ({ ordered_ids: a.orderedIds ?? a.ordered_ids }),
  },
};
