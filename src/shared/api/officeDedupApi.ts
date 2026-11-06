/**
 * Office duplicate-group API (Phase 1 Item A: 文档库重复清理).
 *
 * Backend counterpart: `GET /api/v1/office/documents/duplicate-groups`
 * (`backend/api/office_dedup_routes.py`). Split out of officeApi.ts to
 * keep the aggregate API object under the file-size ratchet.
 */

import { invoke } from './desktopInvoke';
import type { OfficeDuplicateGroupsResult } from './officeDuplicateTypes';
import { handleApiError } from './utils';

export const officeDedupApi = {
  /**
   * List groups of live documents that share identical bytes within a
   * workspace. Powers the "重复" badge and the bulk cleanup action.
   *
   * No retry — read-only but cheap; the UI re-queries explicitly after
   * mutations that might introduce new duplicates.
   */
  async listDuplicateGroups(workspacePath: string): Promise<OfficeDuplicateGroupsResult> {
    try {
      return await invoke<OfficeDuplicateGroupsResult>('office_list_duplicate_groups', {
        workspacePath,
      });
    } catch (error) {
      throw handleApiError(error);
    }
  },
};
