/**
 * Sage API - Skills API (PR-7)
 */

import { invoke } from './desktopInvoke';
import type { DeleteSkillResult, Skill, SkillExecuteRequest, SkillExecuteResult } from './types';
import { handleApiError, withRetry } from './utils';

export const skillsApi = {
  async list(): Promise<Skill[]> {
    return withRetry(async () => {
      try {
        return await invoke<Skill[]>('list_skills');
      } catch (error) {
        throw handleApiError(error);
      }
    });
  },

  async toggle(name: string, enabled: boolean): Promise<Skill> {
    return withRetry(async () => {
      try {
        return await invoke<Skill>('toggle_skill', { name, enabled });
      } catch (error) {
        throw handleApiError(error);
      }
    });
  },

  async execute(name: string, req: SkillExecuteRequest = {}): Promise<SkillExecuteResult> {
    return withRetry(async () => {
      try {
        return await invoke<SkillExecuteResult>('execute_skill', {
          name,
          action: req.action ?? null,
          args: req.args ?? null,
        });
      } catch (error) {
        throw handleApiError(error);
      }
    });
  },
  /**
   * 物理删除一个 SKILL.md 技能 (POST /api/v1/skills/{name}/delete)。
   *
   * Throws on:
   * - 400 builtin / invalid name
   * - 404 missing
   * - 500 filesystem error
   */
  async delete(name: string): Promise<DeleteSkillResult> {
    return withRetry(async () => {
      try {
        return await invoke<DeleteSkillResult>('delete_skill', { name });
      } catch (error) {
        throw handleApiError(error);
      }
    });
  },
};
