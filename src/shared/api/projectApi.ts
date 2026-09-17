/**
 * 项目模块 API 客户端 (P1, 2026-09-13)。
 *
 * "项目" = 用户在侧边栏登记的工作目录（对标 Cursor Recent Workspaces）。
 * 后端契约见 backend/api/project_routes.py；会话归属复用会话工作区绑定。
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
  /**
   * 额外允许访问的路径规则列表。
   * 类 .gitignore 语法（`~/Documents/**`、`/tmp/*` 等）。
   * 默认 []，表示不扩展访问范围。
   */
  allowedPaths: string[];
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
  allowed_paths?: string[];
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
    sessionCount: p.session_count ?? 0,
    lastSessionId: p.last_session_id ?? null,
    allowedPaths: p.allowed_paths ?? [],
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
    // eslint-disable-next-line no-console -- best-effort 同步, 不阻断主流程
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
    // eslint-disable-next-line no-console -- best-effort, 同上
    console.warn('[projectApi] unregister allowed_paths from main failed', { projectId, err });
  }
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
};
