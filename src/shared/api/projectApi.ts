/**
 * 项目模块 API 客户端 (P1, 2026-09-13)。
 *
 * "项目" = 用户在侧边栏登记的工作目录（对标 Cursor Recent Workspaces）。
 * 后端契约见 backend/api/project_routes.py；会话归属复用会话工作区绑定。
 *
 * M3 项目上下文沉淀 (2026-09-15):
 * - ProjectSummary 透出 description/instructions, 供侧边栏概览面板就地编辑
 * - ProjectMaterial 类型 + 资料 CRUD + save-answer(把可见回答固化进项目)
 *
 * 2026-09-17 allowed_paths 扩展：
 * - 项目可配置额外允许访问的路径规则列表（project.allowed_paths）
 * - 支持 .gitignore 风格通配符（`~/Documents/**`、`/tmp/scratch/*`）
 * - 读取遵守 allowed_paths，写入仍限于 workspace 内（读写非对称）
 */

import { invoke } from './desktopInvoke';
import type { Session } from './types';
import { handleApiError } from './utils';

/** 项目清单条目（camelCase，渲染端消费） */
export interface ProjectSummary {
  id: string;
  /** 规范化绝对路径（与 session_workspace_bindings.workspace_path 同口径） */
  path: string;
  /** 目录 basename，会话标题与行展示用 */
  name: string;
  createdAt: number;
  lastOpenedAt: number;
  /** 归属该项目的未归档会话数（活跃绑定聚合） */
  sessionCount: number;
  /** 最近活跃会话 id；无绑定会话时为 null */
  lastSessionId: string | null;
  /** M3: 项目描述 (PATCH /projects/{id})。后端 None 表示未设置 */
  description?: string | null;
  /** M3: 项目指令 (system prompt 注入, 优先级高于全局风格偏好) */
  instructions?: string | null;
  /**
   * 额外允许访问的路径规则列表。
   * 类 .gitignore 语法（`~/Documents/**`、`/tmp/*` 等）。
   * 默认 []，表示不扩展访问范围。
   */
  allowedPaths: string[];
  /** 项目类型分类 (2026-09-24) */
  projectType?: ProjectType | null;
  /** 项目阶段 */
  projectStage?: string | null;
  /** 版本控制模式: 'git' | 'builtin' | 'svn' */
  vcsMode?: string;
  /** 自动检测的项目类型 */
  detectedType?: ProjectType | null;
}

/** 项目类型枚举 */
export type ProjectType = 'coding' | 'research' | 'business' | 'personal';

/** 项目约束实体 (2026-09-24) */
export interface ProjectConstraint {
  id: string;
  projectId: string;
  /** 约束类别 */
  category: string;
  /** 约束内容（自然语言） */
  content: string;
  /** 触发条件（glob 模式或 'always'） */
  triggerPattern?: string | null;
  /** 优先级 1-10，高优先级覆盖低优先级 */
  priority: number;
  /** 是否启用 */
  enabled: boolean;
  createdAt: number;
  updatedAt: number;
}

/** 创建约束请求 */
export interface CreateConstraintPayload {
  category: string;
  content: string;
  triggerPattern?: string;
  priority?: number;
}

/** 更新约束请求 */
export interface UpdateConstraintPayload {
  category?: string;
  content?: string;
  triggerPattern?: string;
  priority?: number;
  enabled?: boolean;
}

/** 项目里程碑实体 (2026-09-24) */
export interface ProjectMilestone {
  id: string;
  projectId: string;
  title: string;
  description?: string | null;
  /** 所属阶段 */
  stage?: string | null;
  /** 截止日期 */
  dueDate?: string | null;
  /** 完成时间 */
  completedAt?: number | null;
  /** 状态: pending | in_progress | completed | blocked */
  status: string;
  /** 排序顺序 */
  sortOrder: number;
  createdAt: number;
}

/** 创建里程碑请求 */
export interface CreateMilestonePayload {
  title: string;
  description?: string;
  stage?: string;
  dueDate?: string;
  status?: string;
  sortOrder?: number;
}

/** 更新里程碑请求 */
export interface UpdateMilestonePayload {
  title?: string;
  description?: string;
  stage?: string;
  dueDate?: string;
  completedAt?: number;
  status?: string;
  sortOrder?: number;
}

/** 项目类型检测结果 */
export interface ProjectTypeDetectionResult {
  detectedType: ProjectType;
  confidence: number;
  signals: string[];
}

/** POST /projects/{id}/open 响应：复用最近会话时 created=false */
export interface ProjectOpenResult {
  project: ProjectSummary;
  session: Session;
  created: boolean;
}

/** M3: 资料当前状态——ready 进入 system prompt, pending_index/failed 被排除 */
export type ProjectMaterialStatus = 'pending_index' | 'ready' | 'failed';

/** M3: 项目资料实体。content 可能很大, UI 默认折叠/截断展示。 */
export interface ProjectMaterial {
  id: string;
  projectId: string;
  /** 来源消息 id（直接 addMaterial 时为 null） */
  sourceMessageId: string | null;
  /** SHA-256 hex, 用于去重 (project_id, content_hash) UNIQUE INDEX */
  contentHash: string;
  content: string;
  status: ProjectMaterialStatus;
  /** 索引落地的 wiki 相对路径；ready 状态通常非空 */
  wikiPagePath: string | null;
  errorMessage: string | null;
  createdAt: number;
}

/** PATCH /projects/{id} 请求体：只传要改的字段, 后端 model_fields_set 语义保留未改字段 */
export interface ProjectUpdatePatch {
  description?: string | null;
  instructions?: string | null;
}

interface ProjectWire {
  id: string;
  path: string;
  name: string;
  created_at: number;
  last_opened_at: number;
  description?: string | null;
  instructions?: string | null;
  session_count?: number;
  last_session_id?: string | null;
  allowed_paths?: string[];
  // Project type classification (2026-09-24)
  project_type?: string | null;
  project_stage?: string | null;
  vcs_mode?: string;
  detected_type?: string | null;
}

interface ProjectListWire {
  projects: ProjectWire[];
}

interface ProjectOpenWire {
  project: ProjectWire;
  session: Session;
  created: boolean;
}

interface ProjectSessionsWire {
  sessions: Session[];
}

interface ProjectMaterialWire {
  id: string;
  project_id: string;
  source_message_id: string | null;
  content_hash: string;
  content: string;
  status: ProjectMaterialStatus;
  wiki_page_path: string | null;
  error_message: string | null;
  created_at: number;
}

interface ProjectMaterialsListWire {
  materials: ProjectMaterialWire[];
}

interface ProjectAllowedPathsWire {
  id: string;
  allowed_paths: string[];
}

function mapProject(p: ProjectWire): ProjectSummary {
  return {
    id: p.id,
    path: p.path,
    name: p.name,
    createdAt: p.created_at,
    lastOpenedAt: p.last_opened_at,
    description: p.description ?? null,
    instructions: p.instructions ?? null,
    sessionCount: p.session_count ?? 0,
    lastSessionId: p.last_session_id ?? null,
    allowedPaths: p.allowed_paths ?? [],
    // Project type classification (2026-09-24)
    projectType: (p.project_type as ProjectType) ?? null,
    projectStage: p.project_stage ?? null,
    vcsMode: p.vcs_mode ?? 'builtin',
    detectedType: (p.detected_type as ProjectType) ?? null,
  };
}

/**
 * P22 (2026-09-17): 把项目的 allowed_paths 同步到主进程 sage-file://
 * 协议注册表。失败不抛（best-effort，仅日志），避免 IPC 异常阻断
 * 项目 API 主流程；渲染端可继续工作，只是图片渲染可能受限。
 */
async function syncAllowedPathsToMain(
  projectId: string,
  paths: ReadonlyArray<string>,
): Promise<void> {
  const api = typeof window !== 'undefined' ? window.electronAPI?.sageFile : undefined;
  if (!api) return;
  try {
    await api.registerAllowedPaths(projectId, [...paths]);
  } catch (err) {
    console.warn('[projectApi] sync allowed_paths to main failed', { projectId, err });
  }
}

/** P22: 从主进程 sage-file 注册表中注销项目级 allowed_paths。 */
async function unregisterAllowedPathsFromMain(projectId: string): Promise<void> {
  const api = typeof window !== 'undefined' ? window.electronAPI?.sageFile : undefined;
  if (!api) return;
  try {
    await api.unregisterAllowedPaths(projectId);
  } catch (err) {
    console.warn('[projectApi] unregister allowed_paths from main failed', { projectId, err });
  }
}

function mapMaterial(m: ProjectMaterialWire): ProjectMaterial {
  return {
    id: m.id,
    projectId: m.project_id,
    sourceMessageId: m.source_message_id,
    contentHash: m.content_hash,
    content: m.content,
    status: m.status,
    wikiPagePath: m.wiki_page_path,
    errorMessage: m.error_message,
    createdAt: m.created_at,
  };
}

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
  async register(path: string, allowedPaths?: string[]): Promise<ProjectSummary> {
    try {
      const project = await invoke<ProjectWire>('projects_register', {
        path,
        allowed_paths: allowedPaths,
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
   * 返回的资料 status=pending_index（待索引）; ready 后会自动进 system prompt。
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
      const response = await invoke<{
        detected_type: string;
        confidence: number;
        signals: string[];
      }>('projects_detect_type', { path });
      return {
        detectedType: response.detected_type as ProjectType,
        confidence: response.confidence,
        signals: response.signals,
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

  /** 更新约束 */
  async updateConstraint(
    constraintId: string,
    payload: UpdateConstraintPayload,
  ): Promise<ProjectConstraint> {
    try {
      const constraint = await invoke<ConstraintWire>('projects_update_constraint', {
        constraintId,
        ...payload,
      });
      return mapConstraint(constraint);
    } catch (error) {
      throw handleApiError(error);
    }
  },

  /** 删除约束 */
  async deleteConstraint(constraintId: string): Promise<boolean> {
    try {
      const response = await invoke<{ removed: boolean }>('projects_delete_constraint', {
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

  /** 更新里程碑 */
  async updateMilestone(
    milestoneId: string,
    payload: UpdateMilestonePayload,
  ): Promise<ProjectMilestone> {
    try {
      const milestone = await invoke<MilestoneWire>('projects_update_milestone', {
        milestoneId,
        ...payload,
      });
      return mapMilestone(milestone);
    } catch (error) {
      throw handleApiError(error);
    }
  },

  /** 删除里程碑 */
  async deleteMilestone(milestoneId: string): Promise<boolean> {
    try {
      const response = await invoke<{ removed: boolean }>('projects_delete_milestone', {
        milestoneId,
      });
      return response.removed;
    } catch (error) {
      throw handleApiError(error);
    }
  },
};

// ===== Wire types for constraints and milestones (2026-09-24) =====

interface ConstraintWire {
  id: string;
  project_id: string;
  category: string;
  content: string;
  trigger_pattern?: string | null;
  priority: number;
  enabled: boolean;
  created_at: number;
  updated_at: number;
}

interface MilestoneWire {
  id: string;
  project_id: string;
  title: string;
  description?: string | null;
  stage?: string | null;
  due_date?: string | null;
  completed_at?: number | null;
  status: string;
  sort_order: number;
  created_at: number;
}

function mapConstraint(c: ConstraintWire): ProjectConstraint {
  return {
    id: c.id,
    projectId: c.project_id,
    category: c.category,
    content: c.content,
    triggerPattern: c.trigger_pattern ?? null,
    priority: c.priority,
    enabled: c.enabled,
    createdAt: c.created_at,
    updatedAt: c.updated_at,
  };
}

function mapMilestone(m: MilestoneWire): ProjectMilestone {
  return {
    id: m.id,
    projectId: m.project_id,
    title: m.title,
    description: m.description ?? null,
    stage: m.stage ?? null,
    dueDate: m.due_date ?? null,
    completedAt: m.completed_at ?? null,
    status: m.status,
    sortOrder: m.sort_order,
    createdAt: m.created_at,
  };
}
