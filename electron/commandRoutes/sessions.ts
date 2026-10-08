/**
 * Session lifecycle, workspace binding, git changes, worktrees & checkpoints IPC commands.
 */
import type { CommandRoute } from '../commands';

const DEFAULT_WORKSPACE_SEARCH_LIMIT = 20;
const MIN_WORKSPACE_SEARCH_LIMIT = 1;
const MAX_WORKSPACE_SEARCH_LIMIT = 50;

function normalizeWorkspaceSearchLimit(value: unknown): number {
  const limit =
    typeof value === 'number' && Number.isFinite(value)
      ? Math.trunc(value)
      : DEFAULT_WORKSPACE_SEARCH_LIMIT;
  return Math.min(MAX_WORKSPACE_SEARCH_LIMIT, Math.max(MIN_WORKSPACE_SEARCH_LIMIT, limit));
}

export const sessionRoutes: Record<string, CommandRoute> = {
  // sessions
  list_sessions: {
    method: 'GET',
    path: (a) => {
      const limit = (a?.limit as number) ?? 100;
      const offset = (a?.offset as number) ?? 0;
      return `/api/v1/sessions?limit=${limit}&offset=${offset}`;
    },
  },
  create_session: { method: 'POST', path: () => '/api/v1/sessions' },
  get_session: {
    method: 'GET',
    path: (a) => `/api/v1/sessions/${encodeURIComponent(String(a.id))}`,
  },
  delete_session: {
    method: 'DELETE',
    path: (a) => `/api/v1/sessions/${encodeURIComponent(String(a.id))}`,
  },
  // M4: session engineering — 上下文压缩 + 会话分叉
  session_compact: {
    method: 'POST',
    path: (a) => `/api/v1/sessions/${encodeURIComponent(String(a.sessionId))}/compact`,
  },
  // Task 11 (2026-09-17): context-isolation — 撤回自动话题切换（删最后一个 separator）
  session_retreat_segment: {
    method: 'POST',
    path: (a) => `/api/v1/sessions/${encodeURIComponent(String(a.sessionId))}/segments/retreat`,
  },
  // R17-A2: 压缩谱系（归档会话列表，新→旧）。sessionApi.getLineage。
  session_lineage: {
    method: 'GET',
    path: (a) => `/api/v1/sessions/${encodeURIComponent(String(a.sessionId))}/lineage`,
  },
  session_fork: {
    method: 'POST',
    path: (a) => `/api/v1/sessions/${encodeURIComponent(String(a.sessionId))}/fork`,
    // 后端 ForkSessionRequest 用 snake_case 字段；省略的参数不下发。
    // beforeMessage (U5'): 开区间截断——复制 atMessageId 之前的消息。
    body: (a) => {
      const body: Record<string, unknown> = {};
      if (a.atMessageId != null) body.at_message_id = a.atMessageId;
      if (a.title != null) body.title = a.title;
      if (a.beforeMessage != null) body.before_message = a.beforeMessage;
      return body;
    },
  },
  // U18: HTML 会话导出 — 后端返回 JSON 信封 {html, filename}，渲染进程
  // 用 Blob 触发下载。body 只下发 theme：ExportSessionRequest extra=forbid，
  // 若走默认 camelToSnake 会把 sessionId 带进 body 触发 422。
  export_session_html: {
    method: 'POST',
    path: (a) => `/api/v1/sessions/${encodeURIComponent(String(a.sessionId))}/export`,
    body: (a) => ({ theme: a.theme ?? 'auto' }),
  },
  // R18-C: Markdown 会话导出 —— 后端同一端点按 format 分派；body 只下发
  // format（extra=forbid，sessionId 走路径参数）。
  export_session_markdown: {
    method: 'POST',
    path: (a) => `/api/v1/sessions/${encodeURIComponent(String(a.sessionId))}/export`,
    body: () => ({ format: 'markdown' }),
  },

  // session workspace binding
  workspace_bind: {
    method: 'PUT',
    path: (a) => `/api/v1/sessions/${encodeURIComponent(String(a.sessionId))}/workspace`,
    body: (a) => ({ workspacePath: a.workspacePath }),
  },
  workspace_get: {
    method: 'GET',
    path: (a) => `/api/v1/sessions/${encodeURIComponent(String(a.sessionId))}/workspace`,
  },
  workspace_revoke: {
    method: 'DELETE',
    path: (a) => `/api/v1/sessions/${encodeURIComponent(String(a.sessionId))}/workspace`,
  },

  workspace_search_files: {
    method: 'GET',
    path: (a) => {
      const sessionId = encodeURIComponent(String(a.sessionId));
      const query = encodeURIComponent(String(a.query));
      const limit = normalizeWorkspaceSearchLimit(a.limit);
      return `/api/v1/sessions/${sessionId}/workspace/files?q=${query}&limit=${limit}`;
    },
  },

  // U1 变更面板 (对标增强第二轮): 会话工作区 git 变更清单 + 按文件 diff,均只读
  workspace_get_changes: {
    method: 'GET',
    path: (a) => `/api/v1/sessions/${encodeURIComponent(String(a.sessionId))}/workspace/changes`,
  },
  workspace_get_changes_diff: {
    method: 'GET',
    path: (a) => {
      const sessionId = encodeURIComponent(String(a.sessionId));
      const path = encodeURIComponent(String(a.path ?? ''));
      const staged = a.staged ? 'true' : 'false';
      return `/api/v1/sessions/${sessionId}/workspace/changes/diff?path=${path}&staged=${staged}`;
    },
  },
  // right-panel R6: 变更面板"预览"视图 —— 工作区文件内容只读
  workspace_get_change_file: {
    method: 'GET',
    path: (a) => {
      const sessionId = encodeURIComponent(String(a.sessionId));
      const path = encodeURIComponent(String(a.path ?? ''));
      return `/api/v1/sessions/${sessionId}/workspace/changes/file?path=${path}`;
    },
  },
  // U19 变更面板可操作化 (对标增强第四轮批次 B): 逐文件/逐 hunk 撤销
  workspace_revert_changes: {
    method: 'POST',
    path: (a) =>
      `/api/v1/sessions/${encodeURIComponent(String(a.sessionId))}/workspace/changes/revert`,
    body: (a) => ({ paths: a.paths, delete_untracked: a.deleteUntracked === true }),
  },
  workspace_revert_change_hunks: {
    method: 'POST',
    path: (a) =>
      `/api/v1/sessions/${encodeURIComponent(String(a.sessionId))}/workspace/changes/revert-hunks`,
    body: (a) => ({ path: a.path, hunk_indices: a.hunkIndices }),
  },
  // 会话级 worktree 模式 (2026-09-18): 分支 picker / worktree 生命周期
  worktree_branches: {
    method: 'GET',
    path: (a) => {
      const sessionId = encodeURIComponent(String(a.sessionId));
      const remote = a.includeRemote === false ? 'false' : 'true';
      return `/api/v1/sessions/${sessionId}/worktree/branches?include_remote=${remote}`;
    },
  },
  worktree_list: {
    method: 'GET',
    path: (a) => `/api/v1/sessions/${encodeURIComponent(String(a.sessionId))}/worktree`,
  },
  worktree_create: {
    method: 'POST',
    path: (a) => `/api/v1/sessions/${encodeURIComponent(String(a.sessionId))}/worktree`,
    body: (a) => ({
      mode: a.mode,
      branch: a.branch,
      base_ref: a.baseRef ?? 'HEAD',
    }),
  },
  worktree_merge: {
    method: 'POST',
    path: (a) => `/api/v1/sessions/${encodeURIComponent(String(a.sessionId))}/worktree/merge`,
    body: (a) => ({ worktree_id: a.worktreeId }),
  },
  worktree_delete: {
    method: 'DELETE',
    path: (a) =>
      `/api/v1/sessions/${encodeURIComponent(String(a.sessionId))}/worktree/${encodeURIComponent(
        String(a.worktreeId),
      )}?delete_branch=${a.deleteBranch === true ? 'true' : 'false'}`,
  },
  // U2' 检查点面板 (对标增强第五轮批次 A): 快照列表 / 手动快照 / 覆盖恢复。
  // restore 语义"只覆盖不删除"由前端 confirm 文案明示;POST body 必须
  // 剥掉路径参数 (后端 extra="forbid",与 workspace_revert_changes 同理)。
  workspace_list_checkpoints: {
    method: 'GET',
    path: (a) =>
      `/api/v1/sessions/${encodeURIComponent(String(a.sessionId))}/workspace/checkpoints`,
  },
  workspace_create_checkpoint: {
    method: 'POST',
    path: (a) =>
      `/api/v1/sessions/${encodeURIComponent(String(a.sessionId))}/workspace/checkpoints`,
    body: () => ({}),
  },
  workspace_restore_checkpoint: {
    method: 'POST',
    path: (a) =>
      `/api/v1/sessions/${encodeURIComponent(String(a.sessionId))}/workspace/checkpoints/restore`,
    body: (a) => ({ checkpoint_id: a.checkpointId }),
  },

  // U8 (批次 B): 会话级模型覆盖 (G5 收尾,只改模型不改端点)
  session_get_model: {
    method: 'GET',
    path: (a) => `/api/v1/sessions/${encodeURIComponent(String(a.sessionId))}/model`,
  },
  session_set_model: {
    method: 'PUT',
    path: (a) => `/api/v1/sessions/${encodeURIComponent(String(a.sessionId))}/model`,
    body: (a) => ({ model: a.model }),
  },
  // U4' (对标增强第五轮批次 A): 会话重命名——后端 PATCH 路由早已存在
  // (SessionUpdate extra="forbid"),只透传 title;置顶仍由既有单独语义覆盖。
  session_update: {
    method: 'PATCH',
    path: (a) => `/api/v1/sessions/${encodeURIComponent(String(a.sessionId))}`,
    body: (a) => {
      const body: Record<string, unknown> = {};
      // R18-B: is_pinned 置顶开关（后端 SessionUpdateIn.is_pinned 已支持）
      if (a.isPinned != null) body.is_pinned = a.isPinned;
      // title 缺省不下发 —— PATCH 只更新显式传入的字段
      if (a.title != null) body.title = a.title;
      return body;
    },
  },

  // 自动归档 sweep（对标 ZCode taskAutoArchive，#1571 批次）：归档 N 天
  // 未活跃的未置顶会话；幂等，可安全重试。
  session_archive_stale: {
    method: 'POST',
    path: () => '/api/v1/sessions/archive-stale',
    body: (a) => ({ days: a.days }),
  },

  // 清空全部归档会话（含消息）——破坏性操作，前端需二次确认。
  session_purge_archived: {
    method: 'POST',
    path: () => '/api/v1/sessions/purge-archived',
  },
};
