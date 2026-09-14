/**
 * 项目模块 API 客户端 (P1, 2026-09-13)。
 *
 * "项目" = 用户在侧边栏登记的工作目录（对标 Cursor Recent Workspaces）。
 * 后端契约见 backend/api/project_routes.py；会话归属复用会话工作区绑定。
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
}

/** POST /projects/{id}/open 响应：复用最近会话时 created=false */
export interface ProjectOpenResult {
  project: ProjectSummary;
  session: Session;
  created: boolean;
}

interface ProjectWire {
  id: string;
  path: string;
  name: string;
  created_at: number;
  last_opened_at: number;
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

function mapProject(p: ProjectWire): ProjectSummary {
  return {
    id: p.id,
    path: p.path,
    name: p.name,
    createdAt: p.created_at,
    lastOpenedAt: p.last_opened_at,
    sessionCount: p.session_count ?? 0,
    lastSessionId: p.last_session_id ?? null,
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
};
