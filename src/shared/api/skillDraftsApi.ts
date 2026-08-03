/**
 * Sage API - Skill Drafts API (Background Review pipeline)
 *
 * Provides CRUD-like operations for skill drafts that are awaiting
 * user approval. Backend endpoints are defined in
 * `backend/api/legacy_routes.py` under `/api/v1/skill-drafts`.
 */

import { invoke } from './desktopInvoke';
import type {
  SkillDraftApproveResponse,
  SkillDraftListResponse,
  SkillDraftRejectResponse,
} from './types';
import { handleApiError, withRetry } from './utils';

export const skillDraftsApi = {
  /**
   * List skill drafts by status.
   *
   * Defaults to `status=pending` (drafts awaiting user review).
   */
  async list(status: string = 'pending'): Promise<SkillDraftListResponse> {
    return withRetry(async () => {
      try {
        return await invoke<SkillDraftListResponse>('list_skill_drafts', {
          status,
        });
      } catch (error) {
        throw handleApiError(error);
      }
    });
  },

  /**
   * Approve a skill draft → writes SKILL.md to disk and marks the
   * draft as `approved`.
   */
  async approve(draftId: string): Promise<SkillDraftApproveResponse> {
    return withRetry(async () => {
      try {
        return await invoke<SkillDraftApproveResponse>('approve_skill_draft', {
          draft_id: draftId,
        });
      } catch (error) {
        throw handleApiError(error);
      }
    });
  },

  /**
   * Reject a skill draft → marks it as `rejected` without writing
   * anything to disk.
   */
  async reject(draftId: string): Promise<SkillDraftRejectResponse> {
    return withRetry(async () => {
      try {
        return await invoke<SkillDraftRejectResponse>('reject_skill_draft', {
          draft_id: draftId,
        });
      } catch (error) {
        throw handleApiError(error);
      }
    });
  },
};
