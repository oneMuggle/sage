import { invoke } from './desktopInvoke';
import type {
  OfficeDocType,
  SessionWorkspaceBinding,
  WorkspaceRevokeResponse,
  WorkspaceSearchKind,
  WorkspaceSearchResponse,
  WorkspaceSearchResult,
} from './types';
import { handleApiError } from './utils';

interface WorkspaceBindingWire {
  session_id: string;
  workspace_path: string;
  generation: number;
  activated_at: number;
  revoked_at: number | null;
}

interface WorkspaceSearchResultWire {
  name: string;
  kind: WorkspaceSearchKind;
  doc_type: OfficeDocType | null;
  doc_id: string | null;
  size_bytes: number;
  needs_import: boolean;
  source_path: string | null;
}

interface WorkspaceBindWireResponse {
  binding: WorkspaceBindingWire;
}

interface WorkspaceGetWireResponse {
  binding: WorkspaceBindingWire | null;
}

interface WorkspaceSearchWireResponse {
  results: WorkspaceSearchResultWire[];
  total: number;
}

/** U1 变更面板 wire 类型（后端 snake_case） */
interface WorkspaceChangesWire {
  branch: string;
  upstream: string;
  ahead: number;
  behind: number;
  clean: boolean;
  /** 2026-10-29: 非 git 工作区 → false（旧后端缺省时按 true 处理） */
  is_git_repo?: boolean;
  changes: Array<{
    index_status: string;
    worktree_status: string;
    path: string;
<<<<<<< HEAD
    /** 2026-10-29: rename/copy 旧路径（porcelain -z 第二段） */
    old_path?: string | null;
=======
>>>>>>> origin/main
    /** right-panel R5: +/- 行数；二进制/统计失败为 null（旧宿主可能缺省） */
    insertions?: number | null;
    deletions?: number | null;
  }>;
}

/** git 变更清单（camelCase,渲染端消费） */
export interface WorkspaceChanges {
  branch: string;
  upstream: string;
  ahead: number;
  behind: number;
  clean: boolean;
  /** 2026-10-29: false = 工作区不是 git 仓库（渲染空态而非报错） */
  isGitRepo?: boolean;
  changes: Array<{
    indexStatus: string;
    worktreeStatus: string;
    path: string;
<<<<<<< HEAD
    /** 2026-10-29: rename/copy 旧路径（仅展示用） */
    oldPath?: string | null;
=======
>>>>>>> origin/main
    /** right-panel R5: +/- 行数（numstat）；二进制/统计失败为 null */
    insertions: number | null;
    deletions: number | null;
  }>;
}

/** unified diff（可能因超长被后端截断） */
export interface WorkspaceDiff {
  diff: string;
  truncated: boolean;
}

/** right-panel R6: 变更面板"预览"视图的工作区文件内容（可能截断） */
export interface WorkspaceFileContent {
  path: string;
  content: string;
  truncated: boolean;
}

/** U19 逐文件撤销结果 */
export interface WorkspaceRevertResult {
  reverted: string[];
  errors: Array<{ path: string; error: string }>;
}

/** U2' 检查点快照元数据（camelCase，渲染端消费） */
export interface WorkspaceCheckpoint {
  checkpointId: string;
  createdAt: string;
  bytes: number;
  files: number | null;
}

/** U2' 手动快照结果 */
export interface WorkspaceCheckpointCreated {
  checkpointId: string;
  files: number;
  skipped: string[];
  bytes: number;
}

/**
 * 工作区健康状态（2026-10-29, P2）。
 *
 * `health` 与后端 `backend/services/workspace_health.py` 的枚举取值一致：
 * `healthy` / `missing` / `not_a_directory` / `inaccessible` / `read_only`。
 */
export interface WorkspaceHealthStatus {
  path: string | null;
  health: string | null;
  detail: string | null;
  writable: boolean;
  isUsable: boolean;
}

interface WorkspaceRevertWire {
  reverted: string[];
  errors: Array<{ path: string; error: string }>;
}

/** U2' 检查点 wire 类型（后端 snake_case） */
interface WorkspaceCheckpointWire {
  checkpoint_id: string;
  created_at: string;
  bytes: number;
  files: number | null;
}

interface WorkspaceCheckpointsWire {
  checkpoints: WorkspaceCheckpointWire[];
}

interface WorkspaceCheckpointCreateWire {
  checkpoint_id: string;
  files: number;
  skipped: string[];
  bytes: number;
}

function mapBinding(binding: WorkspaceBindingWire): SessionWorkspaceBinding {
  return {
    sessionId: binding.session_id,
    workspacePath: binding.workspace_path,
    generation: binding.generation,
    activatedAt: binding.activated_at,
    revokedAt: binding.revoked_at,
  };
}

function mapSearchResult(result: WorkspaceSearchResultWire): WorkspaceSearchResult {
  return {
    name: result.name,
    kind: result.kind,
    docType: result.doc_type,
    docId: result.doc_id,
    sizeBytes: result.size_bytes,
    needsImport: result.needs_import,
    sourcePath: result.source_path,
  };
}

export const workspaceApi = {
  async bind(
    sessionId: string,
    workspacePath: string,
  ): Promise<{ binding: SessionWorkspaceBinding }> {
    try {
      const response = await invoke<WorkspaceBindWireResponse>('workspace_bind', {
        sessionId,
        workspacePath,
      });
      return { binding: mapBinding(response.binding) };
    } catch (error) {
      throw handleApiError(error);
    }
  },

  async get(sessionId: string): Promise<{ binding: SessionWorkspaceBinding | null }> {
    try {
      const response = await invoke<WorkspaceGetWireResponse>('workspace_get', { sessionId });
      return {
        binding: response.binding === null ? null : mapBinding(response.binding),
      };
    } catch (error) {
      throw handleApiError(error);
    }
  },

  async revoke(sessionId: string): Promise<WorkspaceRevokeResponse> {
    try {
      return await invoke<WorkspaceRevokeResponse>('workspace_revoke', { sessionId });
    } catch (error) {
      throw handleApiError(error);
    }
  },

  async search(
    sessionId: string,
    query: string,
    limit: number = 20,
  ): Promise<WorkspaceSearchResponse> {
    try {
      const response = await invoke<WorkspaceSearchWireResponse>('workspace_search_files', {
        sessionId,
        query,
        limit,
      });
      return {
        results: response.results.map(mapSearchResult),
        total: response.total,
      };
    } catch (error) {
      throw handleApiError(error);
    }
  },

  // ===== U1 变更面板 (对标增强第二轮) =====

  /** 会话工作区 git 变更清单（只读；未绑定工作区 / 非 git 仓库时抛错）。 */
  async getChanges(sessionId: string): Promise<WorkspaceChanges> {
    try {
      const response = await invoke<WorkspaceChangesWire>('workspace_get_changes', {
        sessionId,
      });
      return {
        branch: response.branch,
        upstream: response.upstream,
        ahead: response.ahead,
        behind: response.behind,
        clean: response.clean,
        // 2026-10-29: 旧后端不返回该字段 → 按 git 仓库处理（保持原行为）
        isGitRepo: response.is_git_repo ?? true,
        changes: response.changes.map((entry) => ({
          indexStatus: entry.index_status,
          worktreeStatus: entry.worktree_status,
          path: entry.path,
<<<<<<< HEAD
          oldPath: entry.old_path ?? null,
=======
>>>>>>> origin/main
          insertions: entry.insertions ?? null,
          deletions: entry.deletions ?? null,
        })),
      };
    } catch (error) {
      throw handleApiError(error);
    }
  },

  /** 指定文件（或全仓库）的未提交 diff（只读）。 */
  async getChangeDiff(
    sessionId: string,
    path: string = '',
    staged: boolean = false,
  ): Promise<WorkspaceDiff> {
    try {
      return await invoke<WorkspaceDiff>('workspace_get_changes_diff', {
        sessionId,
        path,
        staged,
      });
    } catch (error) {
      throw handleApiError(error);
    }
  },

  /** right-panel R6: 工作区文件内容（变更面板"预览"视图，只读；超长截断）。 */
  async getChangeFile(sessionId: string, path: string): Promise<WorkspaceFileContent> {
    try {
      return await invoke<WorkspaceFileContent>('workspace_get_change_file', {
        sessionId,
        path,
      });
    } catch (error) {
      throw handleApiError(error);
    }
  },

  // ===== U19 逐文件/逐 hunk 撤销 (对标增强第四轮批次 B) =====

  /** 逐文件撤销工作区改动（git checkout --；未跟踪文件需 deleteUntracked）。 */
  async revertChanges(
    sessionId: string,
    paths: string[],
    deleteUntracked = false,
  ): Promise<WorkspaceRevertResult> {
    try {
      const response = await invoke<WorkspaceRevertWire>('workspace_revert_changes', {
        sessionId,
        paths,
        deleteUntracked,
      });
      return {
        reverted: response.reverted,
        errors: response.errors.map((entry) => ({ path: entry.path, error: entry.error })),
      };
    } catch (error) {
      throw handleApiError(error);
    }
  },

  /** 撤销某文件未暂存 diff 的指定 hunk 子集（0-based 序号）。 */
  async revertChangeHunks(
    sessionId: string,
    path: string,
    hunkIndices: number[],
  ): Promise<{ revertedHunks: number }> {
    try {
      const response = await invoke<{ reverted_hunks: number }>('workspace_revert_change_hunks', {
        sessionId,
        path,
        hunkIndices,
      });
      return { revertedHunks: response.reverted_hunks };
    } catch (error) {
      throw handleApiError(error);
    }
  },

  // ===== U2' 检查点面板 (对标增强第五轮批次 A) =====

  /** 工作区检查点快照列表（新→旧；未绑定工作区时抛错）。 */
  async listCheckpoints(sessionId: string): Promise<WorkspaceCheckpoint[]> {
    try {
      const response = await invoke<WorkspaceCheckpointsWire>('workspace_list_checkpoints', {
        sessionId,
      });
      return response.checkpoints.map((entry) => ({
        checkpointId: entry.checkpoint_id,
        createdAt: entry.created_at,
        bytes: entry.bytes,
        files: entry.files,
      }));
    } catch (error) {
      throw handleApiError(error);
    }
  },

  /** 手动创建工作区快照（zip 存 Sage 数据目录，不动工作区）。 */
  async createCheckpoint(sessionId: string): Promise<WorkspaceCheckpointCreated> {
    try {
      const response = await invoke<WorkspaceCheckpointCreateWire>('workspace_create_checkpoint', {
        sessionId,
      });
      return {
        checkpointId: response.checkpoint_id,
        files: response.files,
        skipped: response.skipped,
        bytes: response.bytes,
      };
    } catch (error) {
      throw handleApiError(error);
    }
  },

  /** 覆盖恢复指定快照（只覆盖快照内文件，不删除快照后新建的文件）。 */
  async restoreCheckpoint(sessionId: string, checkpointId: string): Promise<{ restored: number }> {
    try {
      const response = await invoke<{ checkpoint_id: string; restored: number }>(
        'workspace_restore_checkpoint',
        { sessionId, checkpointId },
      );
      return { restored: response.restored };
    } catch (error) {
      throw handleApiError(error);
    }
  },

  // ===== 默认工作区决策链 (2026-10-29, P1) =====
  // 后端成为工作区决策的单一来源；前端不再自行推导。

  /** 解析默认工作区（只读，不绑定）。用于 UI 预览 / 诊断。 */
  async getDefault(options?: {
    sessionId?: string;
    detectedRoot?: string;
  }): Promise<{ path: string | null; source: string | null; isFallback: boolean }> {
    try {
      const response = await invoke<{
        path: string | null;
        source: string | null;
        is_fallback: boolean;
      }>('workspace_default', {
        sessionId: options?.sessionId,
        detectedRoot: options?.detectedRoot,
      });
      return {
        path: response.path,
        source: response.source,
        isFallback: response.is_fallback,
      };
    } catch (error) {
      throw handleApiError(error);
    }
  },

  /** 把用户显式选择的目录写入 ``preferences``（最高优先级输入）。 */
  async setPreference(path: string): Promise<{ path: string | null; stored: boolean }> {
    try {
      const response = await invoke<{ path: string | null; stored: boolean }>(
        'workspace_set_preference',
        { path },
      );
      return response;
    } catch (error) {
      throw handleApiError(error);
    }
  },

  /** 清除用户偏好，下一次 resolve 走 detected/scratch 兜底。 */
  async forgetPreference(): Promise<{ path: string | null; stored: boolean }> {
    try {
      return await invoke<{ path: string | null; stored: boolean }>(
        'workspace_forget_preference',
      );
    } catch (error) {
      throw handleApiError(error);
    }
  },

  /** 工作区健康状态（只读探测目录是否仍可用）。 */
  async getHealth(path: string): Promise<WorkspaceHealthStatus> {
    try {
      const response = await invoke<{
        path: string | null;
        health: string | null;
        detail: string | null;
        writable: boolean;
        is_usable: boolean;
      }>('workspace_health', { path });
      return {
        path: response.path,
        health: response.health,
        detail: response.detail,
        writable: response.writable,
        isUsable: response.is_usable,
      };
    } catch (error) {
      throw handleApiError(error);
    }
  },
};

export function formatWorkspaceBindingSummary(binding: SessionWorkspaceBinding | null): string {
  if (!binding) return 'unbound';
  const state = binding.revokedAt === null ? 'active' : 'revoked';
  return `${binding.sessionId} · ${binding.workspacePath} · gen ${binding.generation} · ${state}`;
}

export function formatWorkspaceBindingJson(binding: SessionWorkspaceBinding | null): string {
  return JSON.stringify(
    {
      schema: 'sage.shared.workspace_binding.v1',
      bound: binding !== null,
      sessionId: binding?.sessionId ?? null,
      workspacePath: binding?.workspacePath ?? null,
      generation: binding?.generation ?? null,
      active: binding !== null && binding.revokedAt === null,
    },
    null,
    2,
  );
}

export function auditWorkspaceApiGovernance(): string {
  return JSON.stringify(
    {
      schema: 'sage.shared.api.workspace_api.governance.v1',
      phase: 'P177',
      supportsCheckpoints: true,
      unboundSummary: formatWorkspaceBindingSummary(null),
    },
    null,
    2,
  );
}
