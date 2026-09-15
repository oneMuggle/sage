/**
 * 项目模块 API 客户端 (P1, 2026-09-13)。
 *
 * "项目" = 用户在侧边栏登记的工作目录（对标 Cursor Recent Workspaces）。
 * 后端契约见 backend/api/project_routes.py；会话归属复用会话工作区绑定。
 *
 * M3 项目上下文沉淀 (2026-09-15):
 * - ProjectSummary 透出 description/instructions, 供侧边栏概览面板就地编辑
 * - ProjectMaterial 类型 + 资料 CRUD + save-answer(把可见回答固化进项目)
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
  };
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
  /** 最近项目清单（按 last_opened_at 新→旧）。 */
  async list(): Promise<ProjectSummary[]> {
    try {
      const response = await invoke<ProjectListWire>('projects_list');
      return response.projects.map(mapProject);
    } catch (error) {
      throw handleApiError(error);
    }
  },

  /** 登记项目目录（后端校验目录存在并规范化；重复登记幂等）。 */
  async register(path: string): Promise<ProjectSummary> {
    try {
      const project = await invoke<ProjectWire>('projects_register', { path });
      return mapProject(project);
    } catch (error) {
      throw handleApiError(error);
    }
  },

  /** 从清单移除项目（不动磁盘文件与任何会话）。 */
  async remove(id: string): Promise<boolean> {
    try {
      const response = await invoke<{ removed: boolean }>('projects_remove', { id });
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
};
