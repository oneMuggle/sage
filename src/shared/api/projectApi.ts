/**
 * 项目模块 API 客户端 (P1, 2026-09-13; Phase P2 扩展, 2026-10-10)。
 *
 * 类型定义与 Wire 映射位于 ./projectApiTypes.ts。
 */

import { invoke } from './desktopInvoke';
import {
  mapConstraint,
  mapMaterial,
  mapMilestone,
  mapProject,
  type ConstraintWire,
  type MilestoneWire,
  type ProjectTypeDetectWire,
  syncAllowedPathsToMain,
  unregisterAllowedPathsFromMain,
  type CreateConstraintPayload,
  type CreateMilestonePayload,
  type ProjectAllowedPathsWire,
  type ProjectCharter,
  type ProjectConstraint,
  type ProjectContextBudget,
  type ProjectDiagnoseResult,
  type ProjectListWire,
  type ProjectMaterial,
  type ProjectMaterialStatus,
  type ProjectMaterialWire,
  type ProjectMaterialsListWire,
  type ProjectMilestone,
  type ProjectOpenResult,
  type ProjectOpenWire,
  type ProjectScaffoldOptions,
  type ProjectScaffoldResult,
  type ProjectSessionsWire,
  type ProjectSummary,
  type ProjectType,
  type ProjectTypeDetectionResult,
  type ProjectUpdatePatch,
  type ProjectWire,
  type ProjectWorkspaceOverview,
  type UpdateConstraintPayload,
  type UpdateMilestonePayload,
  type WorkspaceArtifactItem,
  type RestoreCheckpointResult,
  type WorkspaceCheckpointDetail,
  type WorkspaceCheckpointItem,
  type WorkspaceDirectorySummary,
  // AI 任务分解 M1 (2026-10-12)
  type DecomposeApplyPayload,
  type DecomposePreviewPayload,
  type DecomposePreviewWire,
  type DecomposeApplyWire,
  mapDecomposePreview,
  mapDecomposeApply,
  // AI 知识沉淀 M2 (2026-10-12)
  type ExtractKnowledgePayload,
  type ExtractKnowledgeWire,
  type ConfirmKnowledgePayload,
  type ConfirmKnowledgeWire,
  mapExtractKnowledge,
  mapConfirmKnowledge,
  // AI 项目顾问 M3 (2026-10-12)
  type AdviceWire,
  mapAdvice,
  // AI 代码→Wiki 生成 M5 (2026-10-12)
  type WikiGeneratePayload,
  type WikiGenerateWire,
  type FileScanWire,
  type SymbolExtractWire,
  mapWikiGenerate,
  mapFileScan,
  mapSymbolExtract,
  // M4: 语义检索 (2026-10-12)
  type SemanticSearchWire,
  type IndexingStatsWire,
  mapSemanticSearch,
  mapIndexingStats,
} from './projectApiTypes';

// Re-export AI types for barrel consumption
export type {
  PreviewMilestoneNode,
  DecomposePreviewResult,
  DecomposePreviewPayload,
  DecomposeApplyPayload,
  DecomposeApplyResult,
  // M2
  KnowledgeEntryProposal,
  ExtractKnowledgeResult,
  ExtractKnowledgePayload,
  ConfirmKnowledgePayload,
  ConfirmKnowledgeResult,
  // M3
  AdvisorRisk,
  AdvisorSuggestion,
  AdviceResult,
  // M5
  WikiGeneratePayload,
  WikiGenerateResult,
  ScannedFile,
  FileScanResult,
  ExtractedSymbol,
  SymbolExtractResult,
  // M4: 语义检索 (2026-10-12)
  SemanticSearchHit,
  SemanticSearchResult,
  IndexingStats,
} from './projectApiTypes';
import type { Session } from './types';
import { handleApiError } from './utils';

export type {
  CreateConstraintPayload,
  CreateMilestonePayload,
  ProjectCharter,
  ProjectConstraint,
  ProjectContextBudget,
  ProjectDiagnoseResult,
  ProjectMaterial,
  ProjectMaterialStatus,
  ProjectMilestone,
  ProjectOpenResult,
  ProjectScaffoldOptions,
  ProjectScaffoldResult,
  ProjectSummary,
  ProjectType,
  ProjectTypeDetectionResult,
  ProjectUpdatePatch,
  ProjectWorkspaceOverview,
  UpdateConstraintPayload,
  UpdateMilestonePayload,
  WorkspaceArtifactItem,
  RestoreCheckpointResult,
  WorkspaceCheckpointDetail,
  WorkspaceCheckpointItem,
  WorkspaceDirectorySummary,
};

export const projectApi = {
  /** 最近项目清单（按 last_opened_at 新→旧）。
   *
   * P22: 拉取成功后批量同步各项目的 allowed_paths 到主进程注册表
   * （冷启动/页面刷新后的 rehydrate 入口）。
   */
  async list(): Promise<ProjectSummary[]> {
    try {
      const response = await invoke<ProjectListWire>('projects_list');
      const projects = response.projects.map(mapProject);
      // 批量 fire-and-forget 同步；不阻塞返回
      for (const project of projects) {
        void syncAllowedPathsToMain(project.id, project.allowedPaths);
      }
      return projects;
    } catch (error) {
      throw handleApiError(error);
    }
  },

  /** 登记项目目录（后端校验目录存在并规范化；重复登记幂等）。
   *
   * 2026-09-17: 支持注册时携带 allowed_paths；登记后同步到主进程。
   */
  async register(
    path: string,
    options?: { allowedPaths?: string[]; projectType?: ProjectType },
  ): Promise<ProjectSummary> {
    try {
      const project = await invoke<ProjectWire>('projects_register', {
        path,
        allowed_paths: options?.allowedPaths,
        project_type: options?.projectType,
      });
      const mapped = mapProject(project);
      void syncAllowedPathsToMain(mapped.id, mapped.allowedPaths);
      return mapped;
    } catch (error) {
      throw handleApiError(error);
    }
  },

  /** 从清单移除项目（不动磁盘文件与任何会话）。P22: 注销主进程注册项。 */
  async remove(id: string): Promise<boolean> {
    try {
      const response = await invoke<{ removed: boolean }>('projects_remove', { id });
      if (response.removed) {
        void unregisterAllowedPathsFromMain(id);
      }
      return response.removed;
    } catch (error) {
      throw handleApiError(error);
    }
  },

  /**
   * 打开项目：返回该项目最近活跃会话（created=false），或新建会话并
   * 绑定项目目录（created=true）。目录已在磁盘上消失时抛 410
   * project_path_missing，调用方应提示移除或重选。
   */
  async open(id: string): Promise<ProjectOpenResult> {
    try {
      const response = await invoke<ProjectOpenWire>('projects_open', { id });
      return {
        project: mapProject(response.project),
        session: response.session,
        created: response.created,
      };
    } catch (error) {
      throw handleApiError(error);
    }
  },

  /** 在项目下显式新建一个绑定会话（项目行 hover + 按钮）。 */
  async createSession(id: string): Promise<{ project: ProjectSummary; session: Session }> {
    try {
      const response = await invoke<ProjectOpenWire>('projects_create_session', { id });
      return { project: mapProject(response.project), session: response.session };
    } catch (error) {
      throw handleApiError(error);
    }
  },

  /** 项目下未归档会话（新→旧，上限 20）。 */
  async listSessions(id: string): Promise<Session[]> {
    try {
      const response = await invoke<ProjectSessionsWire>('projects_list_sessions', { id });
      return response.sessions;
    } catch (error) {
      throw handleApiError(error);
    }
  },

  /**
   * M3: 更新项目概览字段（description/instructions）。
   * 后端 Pydantic model_fields_set 语义——只 patch 传入的字段,
   * 缺省字段保持不变（空串/null 也能传, 用于"清空字段"语义）。
   */
  async update(id: string, patch: ProjectUpdatePatch): Promise<ProjectSummary> {
    try {
      const project = await invoke<ProjectWire>('projects_update', { id, ...patch });
      return mapProject(project);
    } catch (error) {
      throw handleApiError(error);
    }
  },

  /** M3: 列出项目所有资料 (按 created_at ASC, 含 pending/ready/failed)。 */
  async listMaterials(id: string): Promise<ProjectMaterial[]> {
    try {
      const response = await invoke<ProjectMaterialsListWire>('projects_list_materials', { id });
      return response.materials.map(mapMaterial);
    } catch (error) {
      throw handleApiError(error);
    }
  },

  /**
   * M3: 直接添加资料(用户粘贴文本/Markdown)。
   * 返回的资料 status=ready（添加即生效, 下一条新消息起注入 system prompt）。
   * 同 (project_id, content_hash) 幂等, 返回已有行。
   */
  async addMaterial(
    id: string,
    payload: { content: string; source_message_id?: string | null },
  ): Promise<ProjectMaterial> {
    try {
      const material = await invoke<ProjectMaterialWire>('projects_add_material', {
        id,
        content: payload.content,
        source_message_id: payload.source_message_id ?? null,
      });
      return mapMaterial(material);
    } catch (error) {
      throw handleApiError(error);
    }
  },

  /** Phase P3: 将工作区内的文献/案卷文件一键提取并纳入受控资料池。 */
  async addMaterialFromFile(id: string, relativePath: string): Promise<ProjectMaterial> {
    try {
      const material = await invoke<ProjectMaterialWire>('projects_add_material_from_file', {
        id,
        relativePath,
      });
      return mapMaterial(material);
    } catch (error) {
      throw handleApiError(error);
    }
  },

  /** Phase P2: 切换资料是否参与系统提示词注入（NotebookLM 式资料源开关）。 */
  async updateMaterial(
    id: string,
    materialId: string,
    patch: { enabled: boolean },
  ): Promise<ProjectMaterial> {
    try {
      const material = await invoke<ProjectMaterialWire>('projects_update_material', {
        id,
        materialId,
        enabled: patch.enabled,
      });
      return mapMaterial(material);
    } catch (error) {
      throw handleApiError(error);
    }
  },

  /** Phase P2: 获取项目五层受控上下文水位统计。 */
  async getContextBudget(projectId: string): Promise<ProjectContextBudget> {
    try {
      const raw = await invoke<{
        project_id: string;
        l1_conventions_chars: number;
        l2_metadata_chars: number;
        l2_constraints_chars: number;
        l3_profile_chars: number;
        l4_materials_chars: number;
        total_chars: number;
        cap_chars: number;
        per_file_cap_chars: number;
        usage_ratio: number;
        active_materials_count: number;
        total_materials_count: number;
        enabled_constraints_count: number;
        synthesized_preview?: string;
      }>('projects_context_budget', { projectId });
      return {
        projectId: raw.project_id,
        l1ConventionsChars: raw.l1_conventions_chars ?? 0,
        l2MetadataChars: raw.l2_metadata_chars ?? 0,
        l2ConstraintsChars: raw.l2_constraints_chars ?? 0,
        l3ProfileChars: raw.l3_profile_chars ?? 0,
        l4MaterialsChars: raw.l4_materials_chars ?? 0,
        totalChars: raw.total_chars ?? 0,
        capChars: raw.cap_chars ?? 16000,
        perFileCapChars: raw.per_file_cap_chars ?? 8000,
        usageRatio: raw.usage_ratio ?? 0,
        activeMaterialsCount: raw.active_materials_count ?? 0,
        totalMaterialsCount: raw.total_materials_count ?? 0,
        enabledConstraintsCount: raw.enabled_constraints_count ?? 0,
        synthesizedPreview: raw.synthesized_preview ?? '',
      };
    } catch (error) {
      throw handleApiError(error);
    }
  },

  /** Phase P4: 获取项目本地运行环境满足度、测试命令入口与 Hooks 信任状态。 */
  async diagnose(projectId: string): Promise<ProjectDiagnoseResult> {
    try {
      const raw = await invoke<{
        project_id: string;
        level: string;
        detected_languages: string[];
        available_runtimes: string[];
        test_commands: string[];
        hooks_config_exists: boolean;
        hooks_count: number;
        hooks_trusted: boolean;
        recommendations: string[];
      }>('projects_diagnose', { projectId });
      return {
        projectId: raw.project_id,
        level: raw.level ?? 'satisfied',
        detectedLanguages: raw.detected_languages ?? [],
        availableRuntimes: raw.available_runtimes ?? [],
        testCommands: raw.test_commands ?? [],
        hooksConfigExists: Boolean(raw.hooks_config_exists),
        hooksCount: raw.hooks_count ?? 0,
        hooksTrusted: Boolean(raw.hooks_trusted),
        recommendations: raw.recommendations ?? [],
      };
    } catch (error) {
      throw handleApiError(error);
    }
  },

  /** Phase P2: 获取多形态项目工作区资产台账（案卷文书、科研文献/实验产物、代码工程指示器）。 */
  async getWorkspaceOverview(projectId: string): Promise<ProjectWorkspaceOverview> {
    try {
      const raw = await invoke<{
        project_id: string;
        has_sage_md: boolean;
        has_hooks_json: boolean;
        checkpoint_count?: number;
        latest_checkpoint_at?: number | null;
        recent_checkpoints?: Array<{
          id: string;
          label: string;
          created_at: number;
          file_count: number;
        }>;
        coding_indicators: string[];
        office_deliverables: Array<{
          name: string;
          relative_path: string;
          ext: string;
          category: string;
          size_bytes: number;
          modified_at: number;
        }>;
        research_artifacts: Array<{
          name: string;
          relative_path: string;
          ext: string;
          category: string;
          size_bytes: number;
          modified_at: number;
        }>;
        directory_summary: Array<{
          name: string;
          file_count: number;
        }>;
      }>('projects_workspace_overview', { projectId });
      return {
        projectId: raw.project_id,
        hasSageMd: Boolean(raw.has_sage_md),
        hasHooksJson: Boolean(raw.has_hooks_json),
        checkpointCount: raw.checkpoint_count ?? 0,
        latestCheckpointAt: raw.latest_checkpoint_at ?? null,
        recentCheckpoints: (raw.recent_checkpoints ?? []).map((cp) => ({
          id: cp.id,
          label: cp.label,
          createdAt: cp.created_at,
          fileCount: cp.file_count,
        })),
        codingIndicators: raw.coding_indicators ?? [],
        officeDeliverables: (raw.office_deliverables ?? []).map((item) => ({
          name: item.name,
          relativePath: item.relative_path,
          ext: item.ext,
          category: item.category,
          sizeBytes: item.size_bytes,
          modifiedAt: item.modified_at,
        })),
        researchArtifacts: (raw.research_artifacts ?? []).map((item) => ({
          name: item.name,
          relativePath: item.relative_path,
          ext: item.ext,
          category: item.category,
          sizeBytes: item.size_bytes,
          modifiedAt: item.modified_at,
        })),
        directorySummary: (raw.directory_summary ?? []).map((d) => ({
          name: d.name,
          fileCount: d.file_count,
        })),
      };
    } catch (error) {
      throw handleApiError(error);
    }
  },

  /** Phase P7: 为项目创建内置版本控制快照检查点。 */
  async createCheckpoint(projectId: string, label?: string): Promise<WorkspaceCheckpointItem> {
    try {
      const raw = await invoke<{
        id: string;
        label: string;
        created_at: number;
        file_count: number;
      }>('projects_create_checkpoint', { projectId, label });
      return {
        id: raw.id,
        label: raw.label,
        createdAt: raw.created_at,
        fileCount: raw.file_count,
      };
    } catch (error) {
      throw handleApiError(error);
    }
  },

  /** Phase P11: 获取指定内置版本控制检查点的文件清单与快照预览内容。 */
  async getCheckpoint(projectId: string, checkpointId: string): Promise<WorkspaceCheckpointDetail> {
    try {
      const raw = await invoke<{
        id: string;
        label: string;
        created_at: number;
        file_count: number;
        files: string[];
        snapshots: Record<string, string>;
      }>('projects_get_checkpoint', { projectId, checkpointId });
      return {
        id: raw.id,
        label: raw.label,
        createdAt: raw.created_at,
        fileCount: raw.file_count,
        files: raw.files ?? [],
        snapshots: raw.snapshots ?? {},
      };
    } catch (error) {
      throw handleApiError(error);
    }
  },

  /** Phase P13: 删除指定内置版本控制检查点快照。 */
  async deleteCheckpoint(projectId: string, checkpointId: string): Promise<boolean> {
    try {
      const res = await invoke<{ removed: boolean }>('projects_delete_checkpoint', {
        projectId,
        checkpointId,
      });
      return Boolean(res.removed);
    } catch (error) {
      throw handleApiError(error);
    }
  },

  /** Phase P9: 将项目还原到指定内置版本控制快照检查点。 */
  async restoreCheckpoint(
    projectId: string,
    checkpointId: string,
  ): Promise<RestoreCheckpointResult> {
    try {
      const raw = await invoke<{
        id: string;
        label: string;
        restored_files: string[];
        restored_at: number;
      }>('projects_restore_checkpoint', { projectId, checkpointId });
      return {
        id: raw.id,
        label: raw.label,
        restoredFiles: raw.restored_files ?? [],
        restoredAt: raw.restored_at,
      };
    } catch (error) {
      throw handleApiError(error);
    }
  },

  /** Phase P10: 读取项目 L1 本地规范文件 SAGE.md 及其推荐模板。 */
  async getCharter(projectId: string): Promise<ProjectCharter> {
    try {
      const raw = await invoke<{
        project_id: string;
        exists: boolean;
        content: string;
        char_count: number;
        recommended_template: string;
      }>('projects_get_charter', { projectId });
      return {
        projectId: raw.project_id,
        exists: Boolean(raw.exists),
        content: raw.content ?? '',
        charCount: raw.char_count ?? 0,
        recommendedTemplate: raw.recommended_template ?? '',
      };
    } catch (error) {
      throw handleApiError(error);
    }
  },

  /** Phase P10: 在线保存项目 L1 本地规范文件 SAGE.md。 */
  async updateCharter(projectId: string, content: string): Promise<ProjectCharter> {
    try {
      const raw = await invoke<{
        project_id: string;
        exists: boolean;
        content: string;
        char_count: number;
        recommended_template: string;
      }>('projects_update_charter', { projectId, content });
      return {
        projectId: raw.project_id,
        exists: Boolean(raw.exists),
        content: raw.content ?? '',
        charCount: raw.char_count ?? 0,
        recommendedTemplate: raw.recommended_template ?? '',
      };
    } catch (error) {
      throw handleApiError(error);
    }
  },

  /** M3: 删除资料(从清单移除, 不动索引文件, ready 状态不再进 system prompt)。 */
  async removeMaterial(id: string, materialId: string): Promise<boolean> {
    try {
      const response = await invoke<{ removed: boolean }>('projects_remove_material', {
        id,
        materialId,
      });
      return response.removed;
    } catch (error) {
      throw handleApiError(error);
    }
  },

  /**
   * M3: 把当前会话中一条可见 assistant 消息保存为项目资料。
   * 后端校验: message 必须属于绑定到该项目的会话(否则 403 message_project_mismatch)。
   * 同 (project_id, content_hash) 幂等。
   */
  async saveAnswerAsMaterial(id: string, messageId: string): Promise<ProjectMaterial> {
    try {
      const material = await invoke<ProjectMaterialWire>('projects_save_answer', {
        id,
        message_id: messageId,
      });
      return mapMaterial(material);
    } catch (error) {
      throw handleApiError(error);
    }
  },

  /**
   * 更新项目的额外允许访问路径规则列表。
   * 2026-09-17 allowed_paths 扩展：用户可在项目详情面板配置规则。
   * 设置为空数组即清除所有规则（回到默认：仅 workspace 内可访问）。
   * P22: 更新成功后同步到主进程 sage-file:// 注册表。
   */
  async updateAllowedPaths(id: string, allowedPaths: string[]): Promise<string[]> {
    try {
      const response = await invoke<ProjectAllowedPathsWire>('projects_update_allowed_paths', {
        id,
        allowed_paths: allowedPaths,
      });
      void syncAllowedPathsToMain(id, response.allowed_paths);
      return response.allowed_paths;
    } catch (error) {
      throw handleApiError(error);
    }
  },

  // ===== Project Type Classification (2026-09-24) =====

  /** 检测项目类型（基于文件特征） */
  async detectType(path: string): Promise<ProjectTypeDetectionResult> {
    try {
      const response = await invoke<ProjectTypeDetectWire>('projects_detect_type', { path });
      return {
        // 无明显特征时后端返回 project_type=null + confidence=0；向导只在置信度 >= 0.7 时才
        // 自动采用，这里回退到中性类型以满足 ProjectType。
        detectedType: (response.project_type ?? 'personal') as ProjectType,
        confidence: response.confidence,
        // 后端是 {type, weight}[]；UI 把它们当作「检测依据」文案直接拼接 / 渲染。
        signals: response.signals.map((signal) => signal.type),
      };
    } catch (error) {
      throw handleApiError(error);
    }
  },

  /** 更新项目类型（手动设置） */
  async updateProjectType(id: string, projectType: ProjectType): Promise<ProjectSummary> {
    try {
      const project = await invoke<ProjectWire>('projects_update_type', {
        id,
        project_type: projectType,
      });
      return mapProject(project);
    } catch (error) {
      throw handleApiError(error);
    }
  },

  /** 按项目形态（coding / business / research / personal）一键初始化标准目录、SAGE.md、默认约束与阶段里程碑 */
  async scaffold(
    projectId: string,
    options: ProjectScaffoldOptions = {},
  ): Promise<ProjectScaffoldResult> {
    try {
      const raw = await invoke<{
        project: ProjectWire;
        created_directories?: string[];
        created_files?: string[];
        imported_constraints_count?: number;
        seeded_milestones_count?: number;
        recommended_templates?: string[];
      }>('projects_scaffold', {
        projectId,
        projectType: options.projectType,
        createDirectories: options.createDirectories,
        createSageMd: options.createSageMd,
        importDefaultConstraints: options.importDefaultConstraints,
        seedDefaultMilestones: options.seedDefaultMilestones,
      });
      return {
        project: mapProject(raw.project),
        createdDirectories: raw.created_directories ?? [],
        createdFiles: raw.created_files ?? [],
        importedConstraintsCount: raw.imported_constraints_count ?? 0,
        seededMilestonesCount: raw.seeded_milestones_count ?? 0,
        recommendedTemplates: raw.recommended_templates ?? [],
      };
    } catch (error) {
      throw handleApiError(error);
    }
  },

  // ===== Project Constraints (2026-09-24) =====

  /** 列出项目的所有约束 */
  async listConstraints(projectId: string): Promise<ProjectConstraint[]> {
    try {
      const response = await invoke<{ constraints: ConstraintWire[] }>(
        'projects_list_constraints',
        { projectId },
      );
      return response.constraints.map(mapConstraint);
    } catch (error) {
      throw handleApiError(error);
    }
  },

  /** 创建约束 */
  async createConstraint(
    projectId: string,
    payload: CreateConstraintPayload,
  ): Promise<ProjectConstraint> {
    try {
      const constraint = await invoke<ConstraintWire>('projects_create_constraint', {
        projectId,
        ...payload,
      });
      return mapConstraint(constraint);
    } catch (error) {
      throw handleApiError(error);
    }
  },

  /** 更新约束（后端按项目校验归属，所以要同时给 projectId） */
  async updateConstraint(
    projectId: string,
    constraintId: string,
    payload: UpdateConstraintPayload,
  ): Promise<ProjectConstraint> {
    try {
      const constraint = await invoke<ConstraintWire>('projects_update_constraint', {
        projectId,
        constraintId,
        ...payload,
      });
      return mapConstraint(constraint);
    } catch (error) {
      throw handleApiError(error);
    }
  },

  /** 删除约束 */
  async deleteConstraint(projectId: string, constraintId: string): Promise<boolean> {
    try {
      const response = await invoke<{ removed: boolean }>('projects_delete_constraint', {
        projectId,
        constraintId,
      });
      return response.removed;
    } catch (error) {
      throw handleApiError(error);
    }
  },

  /** 批量导入约束模板 */
  async importConstraints(projectId: string, category: string): Promise<ProjectConstraint[]> {
    try {
      const response = await invoke<{ constraints: ConstraintWire[] }>(
        'projects_import_constraints',
        { projectId, category },
      );
      return response.constraints.map(mapConstraint);
    } catch (error) {
      throw handleApiError(error);
    }
  },

  // ===== Project Milestones (2026-09-24) =====

  /** 列出项目的所有里程碑 */
  async listMilestones(projectId: string): Promise<ProjectMilestone[]> {
    try {
      const response = await invoke<{ milestones: MilestoneWire[] }>('projects_list_milestones', {
        projectId,
      });
      return response.milestones.map(mapMilestone);
    } catch (error) {
      throw handleApiError(error);
    }
  },

  /** 创建里程碑 */
  async createMilestone(
    projectId: string,
    payload: CreateMilestonePayload,
  ): Promise<ProjectMilestone> {
    try {
      const milestone = await invoke<MilestoneWire>('projects_create_milestone', {
        projectId,
        ...payload,
      });
      return mapMilestone(milestone);
    } catch (error) {
      throw handleApiError(error);
    }
  },

  /** 更新里程碑（后端按项目校验归属，所以要同时给 projectId） */
  async updateMilestone(
    projectId: string,
    milestoneId: string,
    payload: UpdateMilestonePayload,
  ): Promise<ProjectMilestone> {
    try {
      const milestone = await invoke<MilestoneWire>('projects_update_milestone', {
        projectId,
        milestoneId,
        ...payload,
      });
      return mapMilestone(milestone);
    } catch (error) {
      throw handleApiError(error);
    }
  },

  /** 删除里程碑 */
  async deleteMilestone(projectId: string, milestoneId: string): Promise<boolean> {
    try {
      const response = await invoke<{ removed: boolean }>('projects_delete_milestone', {
        projectId,
        milestoneId,
      });
      return response.removed;
    } catch (error) {
      throw handleApiError(error);
    }
  },

  // ── AI 任务分解 M1 (2026-10-12) ──────────────────────────────────────────

  /** AI 任务分解：预览（LLM 生成分解方案，不写入 DB） */
  async decomposePreview(
    projectId: string,
    payload: DecomposePreviewPayload,
  ): Promise<import('./projectApiTypes').DecomposePreviewResult> {
    try {
      const wire = await invoke<DecomposePreviewWire>('projects_decompose_preview', {
        projectId,
        requirement: payload.requirement,
        context: payload.context,
      });
      return mapDecomposePreview(wire);
    } catch (error) {
      throw handleApiError(error);
    }
  },

  /** AI 任务分解：应用（将预览结果写入 DB） */
  async decomposeApply(
    projectId: string,
    payload: DecomposeApplyPayload,
  ): Promise<import('./projectApiTypes').DecomposeApplyResult> {
    try {
      const wire = await invoke<DecomposeApplyWire>('projects_decompose_apply', {
        projectId,
        milestones: payload.milestones,
      });
      return mapDecomposeApply(wire);
    } catch (error) {
      throw handleApiError(error);
    }
  },

  // ── AI 知识沉淀 M2 (2026-10-12) ──────────────────────────────────────────

  /** M2: 知识提取预览（LLM 从会话历史提取建议，不写入 DB） */
  async extractKnowledge(
    projectId: string,
    payload: ExtractKnowledgePayload,
  ): Promise<import('./projectApiTypes').ExtractKnowledgeResult> {
    try {
      const wire = await invoke<ExtractKnowledgeWire>('projects_extract_knowledge', {
        projectId,
        sessionId: payload.sessionId,
        maxMessages: payload.maxMessages ?? 50,
      });
      return mapExtractKnowledge(wire);
    } catch (error) {
      throw handleApiError(error);
    }
  },

  /** M2: 确认知识（将用户勾选的条目写入项目画像） */
  async confirmKnowledge(
    projectId: string,
    payload: ConfirmKnowledgePayload,
  ): Promise<import('./projectApiTypes').ConfirmKnowledgeResult> {
    try {
      const wire = await invoke<ConfirmKnowledgeWire>('projects_confirm_knowledge', {
        projectId,
        entries: payload.entries.map((e) => ({
          content: e.content,
          category: e.category,
          importance: e.importance,
          source_message_ids: e.sourceMessageIds,
          reasoning: e.reasoning,
        })),
      });
      return mapConfirmKnowledge(wire);
    } catch (error) {
      throw handleApiError(error);
    }
  },

  // ── AI 项目顾问 M3 (2026-10-12) ──────────────────────────────────────────

  /** M3: 获取项目健康评分和建议（使用 30min 缓存） */
  async getAdvice(projectId: string): Promise<import('./projectApiTypes').AdviceResult> {
    try {
      const wire = await invoke<AdviceWire>('projects_get_advice', { projectId });
      return mapAdvice(wire);
    } catch (error) {
      throw handleApiError(error);
    }
  },

  /** M3: 强制刷新项目顾问分析（忽略缓存） */
  async refreshAdvice(projectId: string): Promise<import('./projectApiTypes').AdviceResult> {
    try {
      const wire = await invoke<AdviceWire>('projects_refresh_advice', { projectId });
      return mapAdvice(wire);
    } catch (error) {
      throw handleApiError(error);
    }
  },

  // ── AI 代码→Wiki 生成 M5 (2026-10-12) ──────────────────────────────────────

  /** M5: 调用 LLM 生成项目 Wiki 文档 */
  async wikiGenerate(
    projectId: string,
    payload: WikiGeneratePayload,
  ): Promise<import('./projectApiTypes').WikiGenerateResult> {
    try {
      const wire = await invoke<WikiGenerateWire>('projects_wiki_generate', {
        projectId,
        incremental: payload.incremental,
      });
      return mapWikiGenerate(wire);
    } catch (error) {
      throw handleApiError(error);
    }
  },

  /** M5: 预览将被扫描的源文件 */
  async wikiScanFiles(
    projectId: string,
    languages?: string,
  ): Promise<import('./projectApiTypes').FileScanResult> {
    try {
      const wire = await invoke<FileScanWire>('projects_wiki_scan_files', {
        projectId,
        languages: languages ?? 'python',
      });
      return mapFileScan(wire);
    } catch (error) {
      throw handleApiError(error);
    }
  },

  /** M5: 预览将被提取的符号 */
  async wikiExtractSymbols(
    projectId: string,
  ): Promise<import('./projectApiTypes').SymbolExtractResult> {
    try {
      const wire = await invoke<SymbolExtractWire>('projects_wiki_extract_symbols', {
        projectId,
      });
      return mapSymbolExtract(wire);
    } catch (error) {
      throw handleApiError(error);
    }
  },

  // ── M4: 语义检索 (2026-10-12) ─────────────────────────────────────────────

  /** M4: 语义检索项目资料 */
  async semanticSearchMaterials(
    projectId: string,
    query: string,
    topK = 5,
  ): Promise<import('./projectApiTypes').SemanticSearchResult> {
    try {
      const wire = await invoke<SemanticSearchWire>('projects_materials_search', {
        projectId,
        query,
        topK,
      });
      return mapSemanticSearch(wire);
    } catch (error) {
      throw handleApiError(error);
    }
  },

  /** M4: 获取索引统计 */
  async getMaterialIndexingStats(
    projectId: string,
  ): Promise<import('./projectApiTypes').IndexingStats> {
    try {
      const wire = await invoke<IndexingStatsWire>('projects_materials_indexing_stats', {
        projectId,
      });
      return mapIndexingStats(wire);
    } catch (error) {
      throw handleApiError(error);
    }
  },

  /** M4: 重新索引单个材料 */
  async reindexMaterial(projectId: string, materialId: string): Promise<void> {
    try {
      await invoke<void>('projects_material_reindex', {
        projectId,
        materialId,
      });
    } catch (error) {
      throw handleApiError(error);
    }
  },
};
