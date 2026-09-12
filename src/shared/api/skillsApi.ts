/**
 * Sage API - Skills API (PR-7)
 */

import type { ImportResult, RescanResult } from '../types/electron-api';

import { invoke } from './desktopInvoke';
import type {
  ConsolidationAcceptResult,
  ConsolidationScanResult,
  ConsolidationSuggestion,
  DeleteSkillResult,
  Skill,
  SkillExecuteRequest,
  SkillExecuteResult,
} from './types';
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
   * 归档 / 取消归档技能（软标记，可逆；POST /api/v1/skills/{name}/archive）。
   * 归档技能从自动激活 / slash 候选排除，文件不动、可恢复。返回更新后的完整 Skill。
   */
  async archive(name: string, archived: boolean): Promise<Skill> {
    return withRetry(async () => {
      try {
        return await invoke<Skill>('archive_skill', { name, archived });
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
  async importFiles(_paths?: string[]): Promise<ImportResult> {
    return withRetry(async () => {
      try {
        const bridge = window.electronAPI?.skills;
        if (!bridge) {
          throw new Error('skills IPC bridge not available');
        }
        return await bridge.importSkills();
      } catch (error) {
        throw handleApiError(error);
      }
    });
  },

  /**
   * 钉住 / 取消钉住技能（Round 17 管理面）。
   * pin 后 archive 返回 409 `skill_pinned`、巡检不给出该技能的 archive 建议。
   *
   * Backend: POST /api/v1/skills/{name}/pin → `{name, pinned}`。
   */
  async pinSkill(name: string, pinned: boolean): Promise<{ name: string; pinned: boolean }> {
    return withRetry(async () => {
      try {
        return await invoke<{ name: string; pinned: boolean }>('pin_skill', { name, pinned });
      } catch (error) {
        throw handleApiError(error);
      }
    });
  },

  /**
   * 固化巡检：扫描长期未用技能，生成 consolidation 建议（可选自动建 SkillDraft 草稿）。
   *
   * Backend: POST /api/v1/skills/consolidation/scan?auto_draft=N → `{suggestions, scanned, drafts_created}`。
   * LLM 未装配时后端返回 503，由调用方 toast 引导。
   */
  async scanConsolidation(autoDraft = true): Promise<ConsolidationScanResult> {
    return withRetry(async () => {
      try {
        return await invoke<ConsolidationScanResult>('skills_consolidation_scan', {
          autoDraft,
        });
      } catch (error) {
        throw handleApiError(error);
      }
    });
  },

  /**
   * 历史巡检建议列表（审计台账 action=consolidation_note，新→旧）。
   *
   * Backend: GET /api/v1/skills/consolidation/suggestions?limit=N。
   */
  async getConsolidationSuggestions(limit = 50): Promise<ConsolidationSuggestion[]> {
    return withRetry(async () => {
      try {
        return await invoke<ConsolidationSuggestion[]>('skills_consolidation_suggestions', {
          limit,
        });
      } catch (error) {
        throw handleApiError(error);
      }
    });
  },

  /**
   * 采纳巡检建议：按技能名批量归档（已 pin 自动跳过、缺失名字回显 missing）。
   *
   * Backend: POST /api/v1/skills/consolidation/accept → `{archived, skipped_pinned, missing}`。
   */
  async acceptConsolidation(skillNames: string[]): Promise<ConsolidationAcceptResult> {
    return withRetry(async () => {
      try {
        return await invoke<ConsolidationAcceptResult>('skills_consolidation_accept', {
          skillNames,
        });
      } catch (error) {
        throw handleApiError(error);
      }
    });
  },
};
