import type { CommandRoute } from '../commands';

export const skillRoutes: Record<string, CommandRoute> = {

  // skills (PR-7)
  // src/pages/Skills.tsx calls skillsApi.list() / .toggle() / .execute()
  // which route through these IPC names. Backend exposes matching endpoints
  // at backend/api/legacy_routes.py:487-559. Without these entries the
  // /skills page throws UnknownIpcCommandError.
  list_skills: { method: 'GET', path: () => '/api/v1/skills' },
  toggle_skill: {
    method: 'POST',
    path: (a) => `/api/v1/skills/${encodeURIComponent(String(a.name))}/toggle`,
  },
  execute_skill: {
    method: 'POST',
    path: (a) => `/api/v1/skills/${encodeURIComponent(String(a.name))}/execute`,
  },
  delete_skill: {
    method: 'POST',
    path: (a) => `/api/v1/skills/${encodeURIComponent(String(a.name))}/delete`,
  },
  archive_skill: {
    method: 'POST',
    path: (a) => `/api/v1/skills/${encodeURIComponent(String(a.name))}/archive`,
  },
  // R17-A1: 技能 pin / 固化巡检（consolidation）管理面。skillsApi.pinSkill 等。
  // autoDraft 由 path builder 转 snake query；accept 的 body 走 camelToSnakeKeys。
  pin_skill: {
    method: 'POST',
    path: (a) => `/api/v1/skills/${encodeURIComponent(String(a.name))}/pin`,
  },
  skills_consolidation_scan: {
    method: 'POST',
    path: (a) =>
      `/api/v1/skills/consolidation/scan?auto_draft=${
        a?.autoDraft === false ? 'false' : 'true'
      }&mode=${a?.mode === 'auto' ? 'auto' : 'full'}`,
  },
  skills_consolidation_suggestions: {
    method: 'GET',
    path: (a) => {
      const limit = a?.limit != null ? `?limit=${encodeURIComponent(String(a.limit))}` : '';
      return `/api/v1/skills/consolidation/suggestions${limit}`;
    },
  },
  skills_consolidation_accept: {
    method: 'POST',
    path: () => '/api/v1/skills/consolidation/accept',
  },

  // P2-2 (可审计可回滚): 技能演化的审计台账与回滚。后端端点早已存在
  // (backend/api/legacy_skill_draft_routes.py 的 /skills/{name}/audit 与
  // /skills/{name}/rollback)，但此前没有任何前端入口 —— 技能被自动演化改动后，
  // 用户既看不到「谁在什么时候改了什么」，也无法退回上一版。缺这两条 IPC 路由
  // 的话 skillsApi.getAudit / .rollback 会抛 UnknownIpcCommandError。
  skill_audit: {
    method: 'GET',
    path: (a) =>
      `/api/v1/skills/${encodeURIComponent(String(a.name))}/audit?limit=${encodeURIComponent(
        String(a.limit ?? 50),
      )}`,
  },
  skill_rollback: {
    method: 'POST',
    path: (a) => `/api/v1/skills/${encodeURIComponent(String(a.name))}/rollback`,
  },

  // Path B: list user-invocable SKILL.md slash command names.
  // Returns {commands: ["/name1", "/name2", ...]} for skills with
  // user_invocable: true. Used by ChatInput to merge into the slash menu.
  list_slash_commands: { method: 'GET', path: () => '/api/v1/skills/commands' },

  // Background Review: skill drafts approval queue (Task 11)
  // src/pages/Skills.tsx "Pending Drafts" tab calls skillDraftsApi.list/approve/reject
  // which route through these IPC names. Backend endpoints at
  // backend/api/legacy_routes.py:1949-1995.
  list_skill_drafts: {
    method: 'GET',
    path: (a) => {
      const status = a?.status ? `?status=${encodeURIComponent(String(a.status))}` : '';
      return `/api/v1/skill-drafts${status}`;
    },
  },
  approve_skill_draft: {
    method: 'POST',
    path: (a) => `/api/v1/skill-drafts/${encodeURIComponent(String(a.draft_id))}/approve`,
  },
  reject_skill_draft: {
    method: 'POST',
    path: (a) => `/api/v1/skill-drafts/${encodeURIComponent(String(a.draft_id))}/reject`,
  },

  // Background Review: explicit learn trigger (Task 12)
  // src/pages/Chat.tsx onLearn callback invokes learnApi.trigger(sessionId)
  // which routes through this IPC name. Backend endpoint at
  // backend/api/legacy_routes.py:1910 (POST /learn).
  trigger_learn: {
    method: 'POST',
    path: () => '/api/v1/learn',
  },
};
