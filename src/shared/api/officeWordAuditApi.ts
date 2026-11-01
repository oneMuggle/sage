/**
 * Word rule-pack audit/fix API (M2c).
 *
 * Extracted from officeApi.ts to keep that file under the 800-line
 * architecture gate. Same IPC/error posture: read-only calls are retry-free,
 * fix writes and is likewise retry-free.
 */

import { invoke } from './desktopInvoke';
import { handleApiError } from './utils';
import type {
  WordAuditFixRequest,
  WordAuditFixResult,
  WordAuditRequest,
  WordAuditResult,
  WordRulePackListResult,
} from './wordAuditTypes';

export const wordAuditApi = {
  /**
   * List built-in + workspace Word rule packs (M2a backend).
   *
   * GET query strings are not auto-translated by the bridge; the IPC route
   * serializes workspacePath itself.
   */
  async listWordRulePacks(
    params: { workspacePath?: string } = {},
  ): Promise<WordRulePackListResult> {
    try {
      return await invoke<WordRulePackListResult>('office_word_rulepacks_list', {
        ...(params.workspacePath ? { workspacePath: params.workspacePath } : {}),
      });
    } catch (error) {
      throw handleApiError(error);
    }
  },

  /**
   * Run a deterministic rule-pack audit (read-only, M2a backend).
   *
   * The IPC route uses rawBody so nested rule `params` keys are never
   * camelCase-rewritten by the generic body translator.
   */
  async auditWord(req: WordAuditRequest): Promise<WordAuditResult> {
    try {
      return await invoke<WordAuditResult>('office_word_audit', {
        workspacePath: req.workspace_path,
        filePath: req.file_path,
        ...(req.rulepack_id !== undefined ? { rulepackId: req.rulepack_id } : {}),
        ...(req.max_size_bytes !== undefined ? { maxSizeBytes: req.max_size_bytes } : {}),
      });
    } catch (error) {
      throw handleApiError(error);
    }
  },

  /**
   * Apply deterministic fixes and re-audit (M2b backend).
   *
   * Side-effecting (writes a new .docx or atomically replaces the source when
   * overwrite=true) — no retry, consistent with repairWord.
   */
  async fixWord(req: WordAuditFixRequest): Promise<WordAuditFixResult> {
    try {
      return await invoke<WordAuditFixResult>('office_word_audit_fix', {
        workspacePath: req.workspace_path,
        filePath: req.file_path,
        ...(req.rulepack_id !== undefined ? { rulepackId: req.rulepack_id } : {}),
        ...(req.output_filename !== undefined ? { outputFilename: req.output_filename } : {}),
        overwrite: req.overwrite ?? false,
        ...(req.max_size_bytes !== undefined ? { maxSizeBytes: req.max_size_bytes } : {}),
      });
    } catch (error) {
      throw handleApiError(error);
    }
  },
};
