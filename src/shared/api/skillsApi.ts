/**
 * Sage API - Skills API (PR-7)
 */

import type { ImportResult, RescanResult } from '../types/electron-api';

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

  /**
   * 重扫磁盘上的 SKILL.md 目录, 增量加载新增的 SKILL.md 文件。
   * 走 IPC bridge `window.electronAPI.skills.rescanSkills()` →
   * main process `skills:rescan` → POST /api/v1/skills/rescan。
   *
   * Returns `{loaded, skipped, total_loaded}`.
   */
  async rescan(): Promise<RescanResult> {
    return withRetry(async () => {
      try {
        const bridge = window.electronAPI?.skills;
        if (!bridge) {
          throw new Error('skills IPC bridge not available');
        }
        return await bridge.rescanSkills();
      } catch (error) {
        throw handleApiError(error);
      }
    });
  },

  /**
   * 通过 IPC bridge 导入用户选中的 SKILL.md 文件。
   * main process 内部组装 multipart FormData → POST /api/v1/skills/import。
   *
   * Returns `{imported, skipped}` — 部分成功时仍返回 200。
   */
  async importFiles(paths: string[]): Promise<ImportResult> {
    return withRetry(async () => {
      try {
        const bridge = window.electronAPI?.skills;
        if (!bridge) {
          throw new Error('skills IPC bridge not available');
        }
        return await bridge.importSkills(paths);
      } catch (error) {
        throw handleApiError(error);
      }
    });
  },
};
