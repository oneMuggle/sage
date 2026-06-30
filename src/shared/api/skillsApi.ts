/**
 * Sage API - Skills API (PR-7)
 */

import { invoke } from './desktopInvoke';
import type { Skill, SkillExecuteRequest, SkillExecuteResult } from './types';
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
   * Path B: fetch user-invocable SKILL.md skill names for the ChatInput slash menu.
   * Backend returns {commands: ["/name1", "/name2", ...]} where each value is the
   * skill name with a leading "/". We extract just the array so callers can
   * render or filter the names directly.
   */
  async listSlashCommands(): Promise<string[]> {
    return withRetry(async () => {
      try {
        const result = await invoke<{ commands: string[] }>('list_slash_commands');
        return result.commands;
      } catch (error) {
        throw handleApiError(error);
      }
    });
  },
};
