/**
 * Project-type IPC commands — renderer: src/shared/api/projectApi.ts and GitStatusWidget; backend:
 * backend/api/project_routes.py (router prefix /projects, mounted under /api/v1).
 *
 * Unlike the Office commands (dropped by #857) these were never registered: the renderer and the
 * backend for project type / constraints / milestones both landed on 2026-09-24, the bridge
 * entries did not, so every call threw UnknownIpcCommandError.
 *
 * Every request model on the backend is `extra="forbid"`, so bodies are built from explicit field
 * lists instead of forwarding `args` (which also carry path ids and UI-only fields). Unset fields
 * are left out: the PATCH routes use `model_fields_set`, so "absent" keeps the stored value.
 */
import type { CommandRoute } from '../commands';

const enc = (value: unknown): string => encodeURIComponent(String(value));
const projectId = (a: Record<string, unknown>): string => enc(a.projectId ?? a.project_id);
const constraintId = (a: Record<string, unknown>): string => enc(a.constraintId ?? a.constraint_id);
const milestoneId = (a: Record<string, unknown>): string => enc(a.milestoneId ?? a.milestone_id);

/** `wire name -> accepted arg names` (first one that is set wins); unset fields are not sent. */
function pick(
  a: Record<string, unknown>,
  spec: Record<string, readonly string[]>,
): Record<string, unknown> {
  const body: Record<string, unknown> = {};
  for (const [wire, names] of Object.entries(spec)) {
    const name = names.find((n) => a[n] !== undefined);
    if (name !== undefined) body[wire] = a[name];
  }
  return body;
}

// ConstraintCreateRequest / ConstraintUpdateRequest
const CONSTRAINT_CREATE = {
  category: ['category'],
  content: ['content'],
  trigger_pattern: ['triggerPattern', 'trigger_pattern'],
  priority: ['priority'],
} as const;
const CONSTRAINT_UPDATE = { ...CONSTRAINT_CREATE, enabled: ['enabled'] } as const;

// MilestoneCreateRequest has no `status` (the create form's status field is dropped here and the
// milestone starts as "pending"); MilestoneUpdateRequest has no `completedAt`.
const MILESTONE_CREATE = {
  title: ['title'],
  description: ['description'],
  stage: ['stage'],
  due_date: ['dueDate', 'due_date'],
  sort_order: ['sortOrder', 'sort_order'],
} as const;
const MILESTONE_UPDATE = { ...MILESTONE_CREATE, status: ['status'] } as const;

export const projectRoutes: Record<string, CommandRoute> = {
  // ---- project type (2026-09-24) -------------------------------------------------------------
  // Preview only: scans the directory, registers nothing.
  projects_detect_type: {
    method: 'POST',
    path: () => '/api/v1/projects/detect-type',
    body: (a) => ({ path: a.path }),
  },
  // ProjectUpdateRequest.project_type: coding | research | business | personal.
  projects_update_type: {
    method: 'PATCH',
    path: (a) => `/api/v1/projects/${enc(a.id)}`,
    body: (a) => pick(a, { project_type: ['project_type', 'projectType'] }),
  },
  // Project archetype scaffold: initialize standard folders, SAGE.md, constraints, milestones.
  projects_scaffold: {
    method: 'POST',
    path: (a) => `/api/v1/projects/${projectId(a)}/scaffold`,
    body: (a) =>
      pick(a, {
        project_type: ['project_type', 'projectType'],
        create_directories: ['create_directories', 'createDirectories'],
        create_sage_md: ['create_sage_md', 'createSageMd'],
        import_default_constraints: ['import_default_constraints', 'importDefaultConstraints'],
        seed_default_milestones: ['seed_default_milestones', 'seedDefaultMilestones'],
      }),
  },
  // Not-a-repo answers 200 with is_repo=false.
  projects_git_status: {
    method: 'GET',
    path: (a) => `/api/v1/projects/${projectId(a)}/git-status`,
  },

  // ---- constraints ---------------------------------------------------------------------------
  projects_list_constraints: {
    method: 'GET',
    path: (a) => `/api/v1/projects/${projectId(a)}/constraints`,
  },
  projects_create_constraint: {
    method: 'POST',
    path: (a) => `/api/v1/projects/${projectId(a)}/constraints`,
    body: (a) => pick(a, CONSTRAINT_CREATE),
  },
  // The backend scopes constraints to their project (404 when the ids do not belong together),
  // so update and delete need `projectId` as well as `constraintId`.
  projects_update_constraint: {
    method: 'PATCH',
    path: (a) => `/api/v1/projects/${projectId(a)}/constraints/${constraintId(a)}`,
    body: (a) => pick(a, CONSTRAINT_UPDATE),
  },
  projects_delete_constraint: {
    method: 'DELETE',
    path: (a) => `/api/v1/projects/${projectId(a)}/constraints/${constraintId(a)}`,
  },
  // The renderer's `category` is a template name (CONSTRAINT_TEMPLATES key, e.g. "coding");
  // the backend field is called `template`.
  projects_import_constraints: {
    method: 'POST',
    path: (a) => `/api/v1/projects/${projectId(a)}/constraints/import-template`,
    body: (a) => ({ template: a.template ?? a.category }),
  },

  // ---- milestones ----------------------------------------------------------------------------
  projects_list_milestones: {
    method: 'GET',
    path: (a) => `/api/v1/projects/${projectId(a)}/milestones`,
  },
  projects_create_milestone: {
    method: 'POST',
    path: (a) => `/api/v1/projects/${projectId(a)}/milestones`,
    body: (a) => pick(a, MILESTONE_CREATE),
  },
  projects_update_milestone: {
    method: 'PATCH',
    path: (a) => `/api/v1/projects/${projectId(a)}/milestones/${milestoneId(a)}`,
    body: (a) => pick(a, MILESTONE_UPDATE),
  },
  projects_delete_milestone: {
    method: 'DELETE',
    path: (a) => `/api/v1/projects/${projectId(a)}/milestones/${milestoneId(a)}`,
  },

  // 项目模块 P1 (2026-09-13): 最近项目注册表 + 项目内会话。
  // open = "复用最近活跃会话或新建并绑定项目目录"（后端原子完成，返回
  // { project, session, created }），前端拿到 session.id 后 setCurrent + 导航。
  projects_list: {
    method: 'GET',
    path: () => '/api/v1/projects',
  },
  projects_register: {
    method: 'POST',
    path: () => '/api/v1/projects',
    body: (a) => {
      const body: Record<string, unknown> = { path: a.path };
      if (a.allowed_paths !== undefined) body.allowed_paths = a.allowed_paths;
      if (a.project_type !== undefined) body.project_type = a.project_type;
      return body;
    },
  },
  projects_remove: {
    method: 'DELETE',
    path: (a) => `/api/v1/projects/${encodeURIComponent(String(a.id))}`,
  },
  projects_open: {
    method: 'POST',
    path: (a) => `/api/v1/projects/${encodeURIComponent(String(a.id))}/open`,
    body: () => ({}),
  },
  projects_create_session: {
    method: 'POST',
    path: (a) => `/api/v1/projects/${encodeURIComponent(String(a.id))}/sessions`,
    body: () => ({}),
  },
  projects_list_sessions: {
    method: 'GET',
    path: (a) => `/api/v1/projects/${encodeURIComponent(String(a.id))}/sessions`,
  },
  projects_update_allowed_paths: {
    method: 'PUT',
    path: (a) => `/api/v1/projects/${encodeURIComponent(String(a.id))}/allowed-paths`,
    body: (a) => ({ allowed_paths: a.allowed_paths ?? a.allowedPaths ?? [] }),
  },
  // M3 项目上下文沉淀 (2026-09-15): 概览字段编辑 + 资料 CRUD + 保存回答。
  // PATCH 用 model_fields_set 语义——只把前端实际改了/传了的字段写进 body,
  // 没传的字段后端按"未出现"处理, 不清空现有值。
  projects_update: {
    method: 'PATCH',
    path: (a) => `/api/v1/projects/${encodeURIComponent(String(a.id))}`,
    body: (a) => {
      const body: Record<string, unknown> = {};
      if (a.description !== undefined) body.description = a.description;
      if (a.instructions !== undefined) body.instructions = a.instructions;
      if (a.project_type !== undefined) body.project_type = a.project_type;
      else if (a.projectType !== undefined) body.project_type = a.projectType;
      if (a.project_stage !== undefined) body.project_stage = a.project_stage;
      else if (a.projectStage !== undefined) body.project_stage = a.projectStage;
      return body;
    },
  },
  projects_list_materials: {
    method: 'GET',
    path: (a) => `/api/v1/projects/${encodeURIComponent(String(a.id))}/materials`,
  },
  projects_add_material: {
    method: 'POST',
    path: (a) => `/api/v1/projects/${encodeURIComponent(String(a.id))}/materials`,
    body: (a) => ({
      content: a.content,
      source_message_id: a.source_message_id ?? null,
    }),
  },
  projects_remove_material: {
    method: 'DELETE',
    path: (a) =>
      `/api/v1/projects/${encodeURIComponent(String(a.id))}/materials/${encodeURIComponent(String(a.materialId))}`,
  },
  projects_add_material_from_file: {
    method: 'POST',
    path: (a) => `/api/v1/projects/${projectId(a)}/materials/from-file`,
    body: (a) => ({ relative_path: a.relativePath ?? a.relative_path }),
  },
  projects_update_material: {
    method: 'PATCH',
    path: (a) =>
      `/api/v1/projects/${encodeURIComponent(String(a.id ?? a.projectId))}/materials/${encodeURIComponent(String(a.materialId))}`,
    body: (a) => ({ enabled: Boolean(a.enabled) }),
  },
  projects_context_budget: {
    method: 'GET',
    path: (a) => `/api/v1/projects/${projectId(a)}/context-budget`,
  },
  projects_workspace_overview: {
    method: 'GET',
    path: (a) => `/api/v1/projects/${projectId(a)}/workspace-overview`,
  },
  projects_save_answer: {
    method: 'POST',
    path: (a) => `/api/v1/projects/${encodeURIComponent(String(a.id))}/materials/save-answer`,
    body: (a) => ({ message_id: a.message_id }),
  },
};
