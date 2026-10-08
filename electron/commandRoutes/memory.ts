import type { CommandRoute } from '../commands';

export const memoryRoutes: Record<string, CommandRoute> = {
  // B1 (P11): 记忆嵌入器状态 / 切换
  embedder_get_status: {
    method: 'GET',
    path: () => '/api/v1/memory/embedder/status',
  },
  embedder_select: {
    method: 'POST',
    path: () => '/api/v1/memory/embedder/select',
    body: (args) => ({ mode: args.mode }),
  },
  memory_export: {
    method: 'GET',
    path: () => '/api/v1/memory/export',
  },
  memory_import: {
    method: 'POST',
    path: () => '/api/v1/memory/import',
    // 信封即 body（后端 import_memory(payload) 直接收 dict）
    body: (a) => a.payload as Record<string, unknown>,
  },

  // memory
  get_memories: {
    method: 'GET',
    path: (a) => {
      const page = (a?.page as number) ?? 1;
      const pageSize = (a?.pageSize as number) ?? 20;
      const memoryType = a?.memoryType as string | null;
      const offset = a?.offset as number | null;
      const sessionId = a?.sessionId as string | null;
      const params = new URLSearchParams({
        page: String(page),
        page_size: String(pageSize),
      });
      if (memoryType) params.set('type', memoryType);
      // 批次三 step 6 (spec §4.3 line 150):
      // 前端 memoryApi.getMemories() 增加 offset / sessionId 透传,
      // 否则后端 4-way /memory/list 收不到 session 隔离和 offset cursor。
      if (offset !== null && offset !== undefined) {
        params.set('offset', String(offset));
      }
      if (sessionId) {
        params.set('session_id', sessionId);
      }
      return `/api/v1/memory/list?${params.toString()}`;
    },
  },
  // 批次三 step 6 (spec §4.3 line 150):
  // 新增 GET /memory/summaries 端点 — 之前前端 memoryApi.getSessionSummaries()
  // 调用 invoke('get_session_summaries', ...) 找不到映射,直接 404。
  // sessionId 必填(spec step 5 严令禁止"全部 session"视图)。
  get_memory_diagnostics: {
    method: 'GET',
    path: () => '/api/v1/memory/diagnostics',
  },
  get_session_summaries: {
    method: 'GET',
    path: (a) => {
      const sessionId = a?.sessionId as string | null | undefined;
      const page = (a?.page as number) ?? 1;
      const pageSize = (a?.pageSize as number) ?? 20;
      const sid = sessionId ? String(sessionId) : '';
      const params = new URLSearchParams({
        session_id: sid,
        page: String(page),
        page_size: String(pageSize),
      });
      return `/api/v1/memory/summaries?${params.toString()}`;
    },
  },
  delete_memory: { method: 'POST', path: () => '/api/v1/memory/delete' },
  // 对标 S2 (2026-09-13): 记忆写入台账（内联"记住了"提示 + 撤销）
  get_recent_memory_writes: {
    method: 'GET',
    path: (a) => {
      const params = new URLSearchParams({
        session_id: String(a?.sessionId ?? ''),
        after_seq: String((a?.afterSeq as number) ?? 0),
        limit: String((a?.limit as number) ?? 20),
      });
      return `/api/v1/memory/recent-writes?${params.toString()}`;
    },
  },
  undo_memory_write: {
    method: 'POST',
    path: () => '/api/v1/memory/undo-write',
    body: (a) => ({ session_id: a.sessionId, id: a.id }),
  },
  // 对标 S2: 用户画像 CRUD（"关于我"可编辑卡片）
  get_user_profile: { method: 'GET', path: () => '/api/v1/memory/profile' },
  create_user_profile: {
    method: 'POST',
    path: () => '/api/v1/memory/profile',
    body: (a) => ({ content: a.content, category: a.category, importance: a.importance }),
  },
  update_user_profile: {
    method: 'PUT',
    path: (a) => `/api/v1/memory/profile/${encodeURIComponent(String(a?.id ?? ''))}`,
    body: (a) => ({ content: a.content, category: a.category, importance: a.importance }),
  },
  delete_user_profile: {
    method: 'DELETE',
    path: (a) => `/api/v1/memory/profile/${encodeURIComponent(String(a?.id ?? ''))}`,
  },
  // P2 scope 轴: 项目画像 CRUD（项目级 MEMORY.md，归属=工作区绝对路径）
  get_project_profile: {
    method: 'GET',
    path: (a) => {
      const params = new URLSearchParams();
      if (a?.projectKey) params.set('project_key', String(a.projectKey));
      if (a?.sessionId) params.set('session_id', String(a.sessionId));
      const qs = params.toString();
      return `/api/v1/memory/project-profile${qs ? `?${qs}` : ''}`;
    },
  },
  create_project_profile: {
    method: 'POST',
    path: () => '/api/v1/memory/project-profile',
    body: (a) => ({
      content: a.content,
      category: a.category,
      importance: a.importance,
      project_key: a.projectKey,
      session_id: a.sessionId,
    }),
  },
  delete_project_profile: {
    method: 'DELETE',
    path: (a) => `/api/v1/memory/project-profile/${encodeURIComponent(String(a?.id ?? ''))}`,
  },
  // PR-C §5.4: front-end memoryApi.ts 调用 invoke('search_memory'|'save_memory'),
  // 但 commands.ts 没映射 → 前端 404。后端端点已存在 (legacy_routes.py:2479, :2490)。
  search_memory: {
    method: 'GET',
    path: (a) => {
      const params = new URLSearchParams({
        query: String(a?.query ?? ''),
        limit: String((a?.limit as number) ?? 20),
      });
      if (a?.memoryType) params.set('type', String(a.memoryType));
      if (a?.sessionId) params.set('session_id', String(a.sessionId));
      return `/api/v1/memory/search?${params.toString()}`;
    },
  },
  save_memory: {
    method: 'POST',
    path: () => '/api/v1/memory/save',
    // Body 字段: content (required), memory_type?, importance?, tags?
    body: (a) => ({
      content: a.content,
      memory_type: a.memoryType,
      importance: a.importance,
      tags: a.tags,
      ...(a.sessionId ? { session_id: a.sessionId } : {}),
    }),
  },
};
