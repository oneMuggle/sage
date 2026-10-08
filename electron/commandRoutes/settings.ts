import type { CommandRoute } from '../commands';

export const settingsRoutes: Record<string, CommandRoute> = {
  system_backups_list: {
    method: 'GET',
    path: () => '/api/v1/system/backups',
  },
  system_backup_create: {
    method: 'POST',
    path: () => '/api/v1/system/backups',
    body: () => ({}),
  },
  // R21: 备份恢复（下次启动生效）+ 记忆导入
  system_backup_restore: {
    method: 'POST',
    path: (a) => `/api/v1/system/backups/${encodeURIComponent(String(a.name))}/restore`,
    body: () => ({}),
  },

  // settings & preferences
  get_settings: { method: 'GET', path: () => '/api/v1/settings' },
  get_evolution_logs: {
    method: 'GET',
    path: (a) => {
      const limit = a.limit ?? 50;
      const offset = a.offset ?? 0;
      return `/api/v1/evolution/logs?limit=${limit}&offset=${offset}`;
    },
  },
  set_settings: { method: 'PUT', path: () => '/api/v1/settings' },
  get_preference: {
    method: 'GET',
    path: (a) => `/api/v1/preferences/${encodeURIComponent(String(a.key))}`,
  },
  set_preference: {
    method: 'PUT',
    path: (a) => `/api/v1/preferences/${encodeURIComponent(String(a.key))}`,
  },

  // M1 tool security hardening: 工具审批 gate（backend/api/permission_routes.py）。
  // permission_request 流事件到达后,渲染进程弹出 ApprovalDialog;用户点
  // 批准/拒绝 → permissions_answer 应答。pending 端点用于断线重连后补拉。
  permissions_pending: { method: 'GET', path: () => '/api/v1/permissions/pending' },
  // 对标 S3 (2026-09-13): 权限三档 + 会话自动放行审计
  permissions_get_preset: { method: 'GET', path: () => '/api/v1/permissions/preset' },
  permissions_set_preset: {
    method: 'POST',
    path: () => '/api/v1/permissions/preset',
    body: (a) => ({ preset: a.preset }),
  },
  // P2-5 渐进式授权：策略读写。默认关闭，必须由用户在设置页显式开启。
  permissions_get_trust_policy: { method: 'GET', path: () => '/api/v1/permissions/trust-policy' },
  permissions_set_trust_policy: {
    method: 'POST',
    path: () => '/api/v1/permissions/trust-policy',
    body: (a) => ({ enabled: a.enabled, threshold: a.threshold }),
  },
  permissions_answer: {
    method: 'POST',
    path: (a) => `/api/v1/permissions/${encodeURIComponent(String(a.requestId))}/answer`,
    // 后端 ApprovalAnswerBody 是 extra="forbid" — body 里只允许
    // approved/remember;requestId 是路径参数,必须从 body 剥掉,否则 422。
    // (与 workspace_bind 剥 sessionId 同理)
    body: (a) => ({ approved: a.approved, remember: a.remember }),
  },

  // M2 part B: AskUserQuestion 提问 gate（backend/api/question_routes.py）。
  // ask_user_question 流事件到达后,渲染进程弹出 QuestionDialog;用户选择/
  // 填写 → questions_answer 应答。pending 端点用于断线重连后补拉。
  questions_pending: { method: 'GET', path: () => '/api/v1/questions/pending' },
  questions_answer: {
    method: 'POST',
    path: (a) => `/api/v1/questions/${encodeURIComponent(String(a.requestId))}/answer`,
    // 后端 QuestionAnswerBody 是 extra="forbid" — body 里只允许
    // answers/custom;requestId 是路径参数,必须从 body 剥掉,否则 422。
    // (与 permissions_answer 剥 requestId 同理)
    body: (a) => ({
      answers: Array.isArray(a.answers) ? a.answers : [],
      custom: a.custom ?? null,
    }),
  },

  // scheduled tasks (Phase 8)
  scheduled_list_tasks: {
    method: 'GET',
    path: () => '/api/v1/scheduled/tasks',
  },
  scheduled_create_task: {
    method: 'POST',
    path: () => '/api/v1/scheduled/tasks',
  },
  scheduled_update_task: {
    method: 'PATCH',
    path: (a) => `/api/v1/scheduled/tasks/${encodeURIComponent(String(a.id))}`,
  },
  scheduled_delete_task: {
    method: 'DELETE',
    path: (a) => `/api/v1/scheduled/tasks/${encodeURIComponent(String(a.id))}`,
  },
  scheduled_run_task: {
    method: 'POST',
    path: (a) => `/api/v1/scheduled/tasks/${encodeURIComponent(String(a.id))}/run`,
  },
  // R17-B: evolution 任务（固化/巡检等）手动触发面 —— APScheduler 侧 job，
  // 不在 JSON 持久化的用户任务表里，走独立路由。
  scheduled_evolution_tasks: {
    method: 'GET',
    path: () => '/api/v1/scheduled/evolution/tasks',
  },
  scheduled_evolution_run: {
    method: 'POST',
    path: (a) => `/api/v1/scheduled/evolution/${encodeURIComponent(String(a.name))}/run`,
  },

  // todo subsystem (personal todolist)
  todo_list: {
    method: 'GET',
    path: (a) => {
      const params = new URLSearchParams();
      if (a?.status !== undefined && a?.status !== null) {
        params.set('status', String(a.status));
      }
      if (a?.project_tag !== undefined && a?.project_tag !== null) {
        params.set('project_tag', String(a.project_tag));
      }
      if (a?.priority !== undefined && a?.priority !== null) {
        params.set('priority', String(a.priority));
      }
      if (a?.include_completed) params.set('include_completed', 'true');
      if (a?.sort_by !== undefined && a?.sort_by !== null) {
        params.set('sort_by', String(a.sort_by));
      }
      if (a?.sort_order !== undefined && a?.sort_order !== null) {
        params.set('sort_order', String(a.sort_order));
      }
      if (a?.limit !== undefined && a?.limit !== null) {
        params.set('limit', String(a.limit));
      }
      if (a?.offset !== undefined && a?.offset !== null) {
        params.set('offset', String(a.offset));
      }
      const qs = params.toString();
      return `/api/v1/todos${qs ? `?${qs}` : ''}`;
    },
  },
  todo_create: {
    method: 'POST',
    path: () => '/api/v1/todos',
  },
  todo_get: {
    method: 'GET',
    path: (a) => `/api/v1/todos/${encodeURIComponent(String(a.id))}`,
  },
  todo_update: {
    method: 'PUT',
    path: (a) => `/api/v1/todos/${encodeURIComponent(String(a.id))}`,
    // UpdateTodoIn declares `extra = "forbid"` — `id` lives in the URL path,
    // so the PUT body must not carry it (otherwise the backend returns 422).
    body: (a) => {
      const changes: Record<string, unknown> = { ...a };
      delete changes.id;
      return changes;
    },
  },
  todo_delete: {
    method: 'DELETE',
    path: (a) => `/api/v1/todos/${encodeURIComponent(String(a.id))}`,
  },
  todo_complete: {
    method: 'POST',
    path: (a) => `/api/v1/todos/${encodeURIComponent(String(a.id))}/complete`,
  },
  todo_cancel: {
    method: 'POST',
    path: (a) => `/api/v1/todos/${encodeURIComponent(String(a.id))}/cancel`,
  },
  todo_summary: {
    method: 'GET',
    path: () => '/api/v1/todos/summary',
  },
  todo_stats: {
    method: 'GET',
    path: () => '/api/v1/todos/stats',
  },

  // custom CSS theme storage (themeCssClient)
  // Backend theme_router 挂在 /api/v1/theme (与其他 IPC 路由一致)
  theme_list: { method: 'GET', path: () => '/api/v1/theme/list' },
  theme_save: { method: 'POST', path: () => '/api/v1/theme/save' },
  theme_get: {
    method: 'GET',
    path: (a) => `/api/v1/theme/get/${encodeURIComponent(String(a.id))}`,
  },
  theme_delete: { method: 'POST', path: () => '/api/v1/theme/delete' },
  // M6 生态扩展: 用量/成本面板 (backend/services/usage_tracker.py 内存态)
  // L8 PR-A (2026-09-09): 支持 range=today|total 查询参数, 默认 today。
  // L8 PR-B (2026-09-09): range 扩到 today|7d|30d|total。
  // 未传 range 时省略 query string (后端会按 today 默认处理)。
  usage_summary: {
    method: 'GET',
    path: (a) => {
      const range = a?.range as string | undefined;
      if (!range) return '/api/v1/usage';
      return `/api/v1/usage?range=${encodeURIComponent(range)}`;
    },
  },
  // L8 PR-B (2026-09-09): 单次请求详情 (usage_events 分页)
  usage_list_requests: {
    method: 'GET',
    path: (a) => {
      const limit = a?.limit ?? 50;
      const offset = a?.offset ?? 0;
      const sid = a?.sessionId;
      let url = `/api/v1/usage/requests?limit=${limit}&offset=${offset}`;
      if (typeof sid === 'string' && sid) url += `&session_id=${encodeURIComponent(sid)}`;
      return url;
    },
  },
  // L8 PR-C (2026-09-09): 趋势图时序 (按桶聚合)
  usage_trend: {
    method: 'GET',
    path: (a) => {
      const range = (a?.range as string) ?? '7d';
      const sid = a?.sessionId;
      let url = `/api/v1/usage/trend?range=${encodeURIComponent(range)}`;
      if (typeof sid === 'string' && sid) url += `&session_id=${encodeURIComponent(sid)}`;
      return url;
    },
  },
  // L8 PR-C (2026-09-09): CSV 导出 (text/plain)
  usage_export_csv: {
    method: 'GET',
    path: (a) => {
      const range = (a?.range as string) ?? 'total';
      const sid = a?.sessionId;
      let url = `/api/v1/usage/export.csv?range=${encodeURIComponent(range)}`;
      if (typeof sid === 'string' && sid) url += `&session_id=${encodeURIComponent(sid)}`;
      return url;
    },
  },

  // 2026-09-04: 本地开发环境助手 — 复用 ChatService.tools 路径,
  // runtime_exec 在后端经 PermissionEnforcer 审批 (与 bash 同等闸口)。
  // 见 docs/plans/2026-09-04_local-development-assistant.md Stage 4。
  runtime_probe: { method: 'POST', path: () => '/api/v1/runtime/probe' },
  runtime_diagnose: { method: 'POST', path: () => '/api/v1/runtime/diagnose' },
  runtime_exec: { method: 'POST', path: () => '/api/v1/runtime/exec' },
};
