/**
 * 规范书库（M2.5）+ AI 合并审校（M3）API。
 *
 * 与 wordAuditApi 相同的 IPC/错误姿态：读操作与写操作都经 Electron
 * 命令桥；带规则包的请求体在 route 层标记 rawBody，保持 params 等
 * 用户数据不被 camelCase 改写。
 */

import { invoke } from './desktopInvoke';
import type {
  AiReviewHistoryResult,
  AiReviewRequest,
  AiReviewResult,
  AiReviseRequest,
  AiReviseResult,
  OfficeSpecBindingResult,
  OfficeSpecCreateRequest,
  OfficeSpecDetailResult,
  OfficeSpecDocument,
  OfficeSpecExtractRequest,
  OfficeSpecListResult,
  OfficeSpecSaveResult,
  OfficeSpecUpdateRequest,
} from './officeSpecTypes';
import { handleApiError } from './utils';
import type { WordRuleExtractionResult } from './wordAuditTypes';

export const officeSpecApi = {
  /** 列出工作区所有规范书（默认规范书排最前）。 */
  async listSpecs(params: { workspacePath?: string | null } = {}): Promise<OfficeSpecListResult> {
    try {
      return await invoke<OfficeSpecListResult>('office_specs_list', {
        ...(params.workspacePath ? { workspacePath: params.workspacePath } : {}),
      });
    } catch (error) {
      throw handleApiError(error);
    }
  },

  /** 取规范书元数据 + live 规则包（workspacePath 必填：规范书按工作区隔离）。 */
  async getSpec(specId: string, workspacePath: string): Promise<OfficeSpecDetailResult> {
    try {
      return await invoke<OfficeSpecDetailResult>('office_specs_get', {
        specId,
        workspacePath,
      });
    } catch (error) {
      throw handleApiError(error);
    }
  },

  /** 新建规范书：提交草稿规则包（pack）或引用已有 rulepack_id。 */
  async createSpec(req: OfficeSpecCreateRequest): Promise<OfficeSpecSaveResult> {
    try {
      return await invoke<OfficeSpecSaveResult>('office_specs_create', {
        workspacePath: req.workspace_path,
        name: req.name,
        ...(req.pack ? { pack: req.pack } : {}),
        ...(req.rulepack_id ? { rulepackId: req.rulepack_id } : {}),
        ...(req.source_file_path ? { sourceFilePath: req.source_file_path } : {}),
        ...(req.source_content_hash ? { sourceContentHash: req.source_content_hash } : {}),
        isDefault: Boolean(req.is_default),
      });
    } catch (error) {
      throw handleApiError(error);
    }
  },

  /** 部分更新规范书；带 pack 时先另存一份新规则包再绑定。 */
  async updateSpec(specId: string, req: OfficeSpecUpdateRequest): Promise<OfficeSpecSaveResult> {
    try {
      return await invoke<OfficeSpecSaveResult>('office_specs_update', {
        specId,
        workspacePath: req.workspace_path,
        ...(req.name !== undefined ? { name: req.name } : {}),
        ...(req.pack ? { pack: req.pack } : {}),
        ...(req.source_file_path !== undefined ? { sourceFilePath: req.source_file_path } : {}),
        ...(req.source_content_hash !== undefined
          ? { sourceContentHash: req.source_content_hash }
          : {}),
      });
    } catch (error) {
      throw handleApiError(error);
    }
  },

  /** 删除规范书元数据（规则包文件保留）。 */
  async deleteSpec(
    specId: string,
    workspacePath: string,
  ): Promise<{ ok: boolean; spec_id: string; workspace_path: string }> {
    try {
      return await invoke<{ ok: boolean; spec_id: string; workspace_path: string }>(
        'office_specs_delete',
        { specId, workspacePath },
      );
    } catch (error) {
      throw handleApiError(error);
    }
  },

  /** 从说明文件提取草稿规则包（LLM 可选），不落库。 */
  async extractSpec(req: OfficeSpecExtractRequest): Promise<WordRuleExtractionResult> {
    try {
      return await invoke<WordRuleExtractionResult>('office_specs_extract', {
        workspacePath: req.workspace_path,
        filePath: req.file_path,
        ...(req.pack_id ? { packId: req.pack_id } : {}),
        ...(req.pack_name ? { packName: req.pack_name } : {}),
        useLlm: Boolean(req.use_llm),
        ...(req.max_size_bytes ? { maxSizeBytes: req.max_size_bytes } : {}),
      });
    } catch (error) {
      throw handleApiError(error);
    }
  },

  /** 设置为工作区默认规范书。 */
  async activateSpec(specId: string, workspacePath: string): Promise<OfficeSpecDocument> {
    try {
      return await invoke<OfficeSpecDocument>('office_specs_activate', {
        specId,
        workspacePath,
      });
    } catch (error) {
      throw handleApiError(error);
    }
  },

  /** 清除工作区默认规范书。 */
  async clearDefaultSpec(workspacePath: string): Promise<{ ok: boolean; default: unknown }> {
    try {
      return await invoke('office_specs_clear_default', { workspacePath });
    } catch (error) {
      throw handleApiError(error);
    }
  },

  /** 查询文档级绑定 + 生效规范书。 */
  async getDocSpec(docId: string, workspacePath: string): Promise<OfficeSpecBindingResult> {
    try {
      return await invoke<OfficeSpecBindingResult>('office_doc_spec_get', {
        docId,
        workspacePath,
      });
    } catch (error) {
      throw handleApiError(error);
    }
  },

  /** 设置/解除文档级规范书绑定（specId=null 解绑，跟随工作区默认）。 */
  async bindDocSpec(
    docId: string,
    params: { workspacePath: string; specId: string | null },
  ): Promise<OfficeSpecBindingResult> {
    try {
      return await invoke<OfficeSpecBindingResult>('office_doc_spec_bind', {
        docId,
        workspacePath: params.workspacePath,
        specId: params.specId,
      });
    } catch (error) {
      throw handleApiError(error);
    }
  },

  /** 跑一次「规范书 + LLM」合并审校。 */
  async runAiReview(req: AiReviewRequest): Promise<AiReviewResult> {
    try {
      return await invoke<AiReviewResult>('office_ai_review', {
        workspacePath: req.workspace_path,
        ...(req.file_path ? { filePath: req.file_path } : {}),
        ...(req.doc_id ? { docId: req.doc_id } : {}),
        ...(req.spec_id ? { specId: req.spec_id } : {}),
        ...(req.scope ? { scope: req.scope } : {}),
        useLlm: req.use_llm !== false,
        ...(req.max_issues ? { maxIssues: req.max_issues } : {}),
        ...(req.max_size_bytes ? { maxSizeBytes: req.max_size_bytes } : {}),
      });
    } catch (error) {
      throw handleApiError(error);
    }
  },

  /** 列出文档的审校历史（最新在前）。 */
  async listAiReviews(
    docId: string,
    params: { workspacePath?: string | null; limit?: number } = {},
  ): Promise<AiReviewHistoryResult> {
    try {
      return await invoke<AiReviewHistoryResult>('office_doc_ai_reviews', {
        docId,
        ...(params.workspacePath ? { workspacePath: params.workspacePath } : {}),
        ...(params.limit ? { limit: params.limit } : {}),
      });
    } catch (error) {
      throw handleApiError(error);
    }
  },

  /** 将选中的审校问题应用为 Word 修订痕迹（自动快照前置）。 */
  async reviseAiIssues(req: AiReviseRequest): Promise<AiReviseResult> {
    try {
      return await invoke<AiReviseResult>('office_ai_revise', {
        workspacePath: req.workspace_path,
        ...(req.file_path ? { filePath: req.file_path } : {}),
        ...(req.doc_id ? { docId: req.doc_id } : {}),
        issues: req.issues,
        ...(req.output_filename ? { outputFilename: req.output_filename } : {}),
        ...(req.author ? { author: req.author } : {}),
        addComments: req.add_comments !== false,
      });
    } catch (error) {
      throw handleApiError(error);
    }
  },
};
