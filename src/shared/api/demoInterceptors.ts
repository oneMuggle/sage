import {
  asNum,
  asStr,
  DEMO_AUDIT_T0,
  DEMO_AUDIT_T1,
  DEMO_AUDIT_T2,
  DEMO_KNOWLEDGE_DOCS,
  DEMO_LANE_BOARD,
  DEMO_LANE_EVENTS,
  DEMO_LANES,
  DEMO_MEMORIES,
  DEMO_SESSION_MEETING_ID,
  DEMO_SESSION_PPT_ID,
  DEMO_SESSION_SURVEY_ID,
  DEMO_SKILLS,
  DEMO_SURVEY_REPORT_MD,
  DEMO_WORKSPACE_PATH,
  demoUUID,
  NOW_S,
} from './demoFixturesCore';
import {
  DEMO_AGENTS,
  DEMO_SCHEDULED_TASKS,
  DEMO_SKILL_RUN_OUTPUT,
  DEMO_SURVEY_SUMMARIES,
  DEMO_USAGE,
  demoMessages,
  demoSessions,
} from './demoFixturesSessionsAndAgents';
import { isDemoMode } from './demoFlag';
import { createDemoOfficeAndSystemHandlers } from './demoOfficeAndSystemHandlers';
import type {
  AgentProfile,
  CreateLanesResponse,
  DeleteSkillResult,
  Memory,
  Message,
  ScheduledTask,
  Session,
  SessionCompactResult,
  SessionExportResult,
  Skill,
  SkillExecuteResult,
} from './types';

export {
  DEMO_KNOWLEDGE_DOCS,
  DEMO_LANE_BOARD,
  DEMO_LANE_EVENTS,
  DEMO_LANES,
  DEMO_MEMORIES,
  DEMO_SESSION_MEETING_ID,
  DEMO_SESSION_PPT_ID,
  DEMO_SESSION_SURVEY_ID,
  DEMO_SKILLS,
  DEMO_SURVEY_REPORT_MD,
  DEMO_WORKSPACE_PATH,
  isDemoMode,
};

let demoSkills: Skill[] = [...DEMO_SKILLS];
let demoAgents: AgentProfile[] = [...DEMO_AGENTS];
let demoMemories: Memory[] = [...DEMO_MEMORIES];
let demoScheduled: ScheduledTask[] = [...DEMO_SCHEDULED_TASKS];

const demoPreferences = new Map<string, string>();

// ─────────────────────────────────────────────────────────────────────────
// 通道注册表
//
// 绝不注册 get_settings / set_settings — 保持真实设置 (含演示开关本身).
// ─────────────────────────────────────────────────────────────────────────

const demoHandlers: Record<string, (args: Record<string, unknown>) => unknown> = {
  // ── Preferences (KV) ──
  // 后端不在 → 内存 KV。未写入过的键返回 value:null, 调用方走各自默认值
  // (与后端未设置时的行为一致, 如 theme_mode / permission_mode)。
  get_preference: (args) => {
    const key = asStr(args.key);
    const stored = demoPreferences.get(key);
    if (stored !== undefined) {
      return { value: stored, value_type: 'string', category: 'ui' };
    }
    if (key === 'current_session_id') {
      return { value: DEMO_SESSION_SURVEY_ID, value_type: 'string', category: 'ui' };
    }
    return { value: null, value_type: 'string', category: 'ui' };
  },
  set_preference: (args) => {
    const key = asStr(args.key);
    const value = typeof args.value === 'string' ? args.value : '';
    demoPreferences.set(key, value);
    return { ok: true };
  },

  // ── 会话 ──
  list_sessions: () => [...demoSessions],

  create_session: (args) => {
    const nowMs = Date.now();
    const session: Session = {
      id: demoUUID(),
      title: asStr(args.title) || '新会话',
      created_at: nowMs,
      updated_at: nowMs,
      last_message_at: null,
      message_count: 0,
      is_pinned: false,
    };
    demoSessions.unshift(session);
    demoMessages.set(session.id, []);
    return session;
  },

  get_session: (args) => {
    const id = asStr(args.sessionId) || asStr(args.id);
    return demoSessions.find((s) => s.id === id) ?? null;
  },

  delete_session: (args) => {
    const id = asStr(args.id) || asStr(args.sessionId);
    const index = demoSessions.findIndex((s) => s.id === id);
    if (index >= 0) demoSessions.splice(index, 1);
    demoMessages.delete(id);
    return { ok: true };
  },

  get_messages: (args) => [...(demoMessages.get(asStr(args.sessionId)) ?? [])],

  delete_message: (args) => {
    const messageId = asStr(args.messageId) || asStr(args.id);
    for (const [sessionId, list] of demoMessages) {
      const index = list.findIndex((m) => m.id === messageId);
      if (index >= 0) {
        list.splice(index, 1);
        const session = demoSessions.find((s) => s.id === sessionId);
        if (session) session.message_count = Math.max(0, session.message_count - 1);
        break;
      }
    }
    return { ok: true };
  },

  session_compact: (args) => {
    const id = asStr(args.sessionId) || asStr(args.id);
    const list = demoMessages.get(id) ?? [];
    const before = list.length;
    const after = Math.min(before, 2);
    const result: SessionCompactResult = {
      ok: true,
      compacted: before > after,
      before,
      after,
      removed: Math.max(0, before - after),
    };
    if (before > after) demoMessages.set(id, [list[0], list[list.length - 1]]);
    return result;
  },

  export_session_html: (args) => {
    const id = asStr(args.sessionId) || asStr(args.id);
    const session = demoSessions.find((s) => s.id === id);
    const list = demoMessages.get(id) ?? [];
    const escape = (text: string) =>
      text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    const body = list
      .map((m) => `<h3>${escape(m.role)}</h3><div>${escape(m.content)}</div>`)
      .join('');
    const result: SessionExportResult = {
      html: `<!DOCTYPE html><html><head><meta charset="utf-8"><title>${escape(session?.title ?? '会话导出')}</title></head><body><h1>${escape(session?.title ?? '')}</h1>${body}</body></html>`,
      filename: `sage-session-${id.slice(0, 8)}.html`,
      session_id: id,
      message_count: list.length,
      theme: 'auto',
    };
    return result;
  },

  // ── 记忆 ──
  get_memories: (args) => {
    const layer = asStr(args.memoryType) || 'all';
    const sessionId = asStr(args.sessionId);
    let list = demoMemories;
    if (layer && layer !== 'all') list = list.filter((m) => (m.layer ?? m.memory_type) === layer);
    if (sessionId) list = list.filter((m) => m.session_id === sessionId);
    const pageSize = Math.min(100, Math.max(1, asNum(args.pageSize, 20)));
    const offset =
      args.offset != null
        ? Math.max(0, asNum(args.offset, 0))
        : (Math.max(1, asNum(args.page, 1)) - 1) * pageSize;
    const items = list.slice(offset, offset + pageSize);
    const breakdown: Record<string, number> = {
      episodic: 0,
      semantic: 0,
      working: 0,
      session_summary: 0,
    };
    for (const m of list) {
      const key = m.layer ?? m.memory_type;
      if (key && key in breakdown) breakdown[key] += 1;
    }
    return {
      items,
      total: list.length,
      page: Math.max(1, asNum(args.page, 1)),
      page_size: pageSize,
      offset,
      layer: layer || 'all',
      source_breakdown: breakdown,
    };
  },

  search_memory: (args) => searchDemoMemories(asStr(args.query)),

  save_memory: (args) => {
    const nowMs = Date.now();
    const memoryType = args.memoryType === 'episodic' ? 'episodic' : 'semantic';
    const memory: Memory = {
      id: demoUUID(),
      content: asStr(args.content),
      memory_type: memoryType,
      layer: memoryType,
      source: memoryType,
      importance: Math.min(10, Math.max(0, asNum(args.importance, 5))),
      tags: Array.isArray(args.tags)
        ? (args.tags.filter((t) => typeof t === 'string') as string[])
        : [],
      created_at: nowMs,
      created_at_ms: nowMs,
      access_count: 0,
    };
    demoMemories = [memory, ...demoMemories];
    return memory;
  },

  delete_memory: (args) => {
    const id = asStr(args.id);
    demoMemories = demoMemories.filter((m) => m.id !== id);
    return { ok: true };
  },

  get_session_summaries: (args) => {
    const sessionId = asStr(args.sessionId);
    const items = DEMO_SURVEY_SUMMARIES.filter((m) => m.session_id === sessionId);
    return {
      session_id: sessionId,
      items,
      total: items.length,
      page: 1,
      page_size: 20,
      offset: 0,
    };
  },

  // ── 知识库 ──
  list_knowledge_docs: () => [...DEMO_KNOWLEDGE_DOCS],

  search_knowledge_docs: (args) => {
    const query = asStr(args.query).toLowerCase();
    return DEMO_KNOWLEDGE_DOCS.filter(
      (d) =>
        d.title.toLowerCase().includes(query) ||
        (d.description ?? '').toLowerCase().includes(query) ||
        (d.tags ?? []).some((t) => t.toLowerCase().includes(query)),
    );
  },

  // ── 技能 ──
  list_skills: () => [...demoSkills],

  toggle_skill: (args) => {
    const name = asStr(args.name);
    demoSkills = demoSkills.map((s) =>
      s.name === name
        ? { ...s, enabled: typeof args.enabled === 'boolean' ? args.enabled : !s.enabled }
        : s,
    );
    return demoSkills.find((s) => s.name === name) ?? null;
  },

  archive_skill: (args) => {
    const name = asStr(args.name);
    const archived = args.archived !== false;
    demoSkills = demoSkills.map((s) =>
      s.name === name ? { ...s, lifecycle: archived ? 'archived' : 'stale' } : s,
    );
    return demoSkills.find((s) => s.name === name) ?? null;
  },

  delete_skill: (args) => {
    const name = asStr(args.name);
    demoSkills = demoSkills.filter((s) => s.name !== name);
    const result: DeleteSkillResult = { deleted: true, name, base_dir: `/skills/${name}` };
    return result;
  },

  // P2-2 技能审计 / 回滚（demo 模式）。不注册的话 demo 模式下点「历史」会抛
  // 「演示模式不支持该后端操作」—— 演示模式也要能走通全流程，不能只让真后端可用。
  skill_audit: (args) => {
    const name = asStr(args.name);
    return {
      skill_name: name,
      entries: [
        {
          id: 1,
          skill_name: name,
          action: 'create',
          actor: 'system',
          source: 'builtin',
          created_at: DEMO_AUDIT_T0,
        },
        {
          id: 2,
          skill_name: name,
          action: 'consolidation_note',
          actor: 'system',
          source: 'consolidation_scan',
          created_at: DEMO_AUDIT_T1,
        },
        {
          id: 3,
          skill_name: name,
          action: 'update',
          actor: 'user',
          source: 'editor',
          created_at: DEMO_AUDIT_T2,
        },
      ],
    };
  },

  skill_rollback: (args) => {
    const name = asStr(args.name);
    return { status: 'rolled_back', skill_name: name };
  },

  execute_skill: () => {
    const result: SkillExecuteResult = {
      success: true,
      content: DEMO_SKILL_RUN_OUTPUT,
      metadata: { duration_ms: 2340 },
    };
    return result;
  },

  list_slash_commands: () => ({
    commands: demoSkills
      .filter((s) => s.enabled && s.source === 'skillmd' && s.lifecycle !== 'archived')
      .map((s) => `/${s.name}`),
  }),

  list_skill_drafts: () => [],

  approve_skill_draft: () => ({ ok: true }),
  reject_skill_draft: () => ({ ok: true }),

  // ── Agents ──
  list_agents: () => [...demoAgents],

  toggle_agent: (args) => {
    const id = asStr(args.id) || asStr(args.agentId);
    demoAgents = demoAgents.map((a) =>
      a.id === id
        ? { ...a, enabled: typeof args.enabled === 'boolean' ? args.enabled : !a.enabled }
        : a,
    );
    return demoAgents.find((a) => a.id === id) ?? null;
  },

  update_agent: (args) => {
    const id = asStr(args.id) || asStr(args.agentId);
    const rawUpdate =
      args.update && typeof args.update === 'object'
        ? (args.update as Record<string, unknown>)
        : {};
    const patch = { ...rawUpdate };
    delete patch.id;
    demoAgents = demoAgents.map((a) => (a.id === id ? { ...a, ...patch, updated_at: NOW_S } : a));
    return demoAgents.find((a) => a.id === id) ?? null;
  },

  // ── 编排 ──
  orchestration_board: () => DEMO_LANE_BOARD,
  orchestration_list_lanes: () => [...DEMO_LANES],
  orchestration_get_lane: (args) =>
    DEMO_LANES.find((l) => l.lane_id === asStr(args.lane_id)) ?? null,
  orchestration_list_lane_events: (args) =>
    DEMO_LANE_EVENTS.filter((e) => e.lane_id === asStr(args.lane_id)),

  orchestration_create_lane: (args) => {
    const response: CreateLanesResponse = {
      ok: true,
      team_id: 'team-demo-01',
      lanes: DEMO_LANES.slice(0, 2),
      tasks: [
        {
          task_id: 'task-demo-001',
          name: asStr(args.goal) || '文献收集',
          description: '检索 PubMed/arXiv 并去重初筛',
          task_type: 'analysis',
          status: 'running',
          blocked_by: [],
          team_id: 'team-demo-01',
          agent_hint: 'executor-a',
        },
        {
          task_id: 'task-demo-002',
          name: '核心文献精读',
          description: '提取 23 篇文献的方法/数据集/结论',
          task_type: 'analysis',
          status: 'created',
          blocked_by: ['task-demo-001'],
          team_id: 'team-demo-01',
          agent_hint: 'executor-b',
        },
      ],
    };
    return response;
  },

  orchestration_cancel_lane: () => ({ ok: true }),
  orchestration_cancel_run: () => ({ ok: true }),
  orchestration_update_plan: () => ({ ok: true }),

  // ── 定时任务 ──
  scheduled_list_tasks: () => [...demoScheduled],

  scheduled_create_task: (args) => {
    const input =
      args.input && typeof args.input === 'object' ? (args.input as Record<string, unknown>) : args;
    const task: ScheduledTask = {
      id: demoUUID(),
      name: asStr(input.name) || '定时任务',
      type: input.type === 'once' ? 'once' : 'recurring',
      schedule:
        input.schedule && typeof input.schedule === 'object'
          ? (input.schedule as ScheduledTask['schedule'])
          : { kind: 'recurring', cron: '0 9 * * *' },
      session_id: asStr(input.session_id) || DEMO_SESSION_SURVEY_ID,
      content: asStr(input.content),
      enabled: true,
      last_run: null,
      next_run: NOW_S + 3600 * 12,
      created_at: NOW_S,
    };
    demoScheduled = [...demoScheduled, task];
    return task;
  },

  scheduled_update_task: (args) => {
    const id = asStr(args.id);
    const changes =
      args.changes && typeof args.changes === 'object'
        ? (args.changes as Record<string, unknown>)
        : {};
    demoScheduled = demoScheduled.map((t) => (t.id === id ? { ...t, ...changes, id: t.id } : t));
    return demoScheduled.find((t) => t.id === id) ?? null;
  },

  scheduled_delete_task: (args) => {
    const id = asStr(args.id);
    demoScheduled = demoScheduled.filter((t) => t.id !== id);
    return null;
  },

  scheduled_run_task: (args) => {
    const id = asStr(args.id);
    demoScheduled = demoScheduled.map((t) => (t.id === id ? { ...t, last_run: NOW_S } : t));
    return demoScheduled.find((t) => t.id === id) ?? null;
  },

  // ── 用量 ──
  usage_summary: () => DEMO_USAGE,

  // ── Workspace (Office 页前置) ──
  workspace_get: (args) => ({
    binding: {
      session_id: asStr(args.sessionId) || DEMO_SESSION_SURVEY_ID,
      workspace_path: DEMO_WORKSPACE_PATH,
      generation: 3,
      activated_at: NOW_S - 86400,
      revoked_at: null,
    },
  }),

  workspace_bind: (args) => ({
    binding: {
      session_id: asStr(args.sessionId) || DEMO_SESSION_SURVEY_ID,
      workspace_path: asStr(args.workspacePath) || DEMO_WORKSPACE_PATH,
      generation: 4,
      activated_at: NOW_S,
      revoked_at: null,
    },
  }),

  workspace_revoke: () => ({ revoked: true, generation: 5 }),

  workspace_search_files: () => ({
    results: [
      {
        name: '文献清单-初筛-86篇.csv',
        kind: 'file',
        doc_type: null,
        doc_id: null,
        size_bytes: 48213,
        needs_import: false,
        source_path: `${DEMO_WORKSPACE_PATH}/data/文献清单-初筛-86篇.csv`,
      },
      {
        name: '文献综述报告-大模型医学应用.docx',
        kind: 'office-word',
        doc_type: 'word',
        doc_id: 'of-1',
        size_bytes: 42381,
        needs_import: false,
        source_path: null,
      },
      {
        name: '检索策略与纳入排除标准.pdf',
        kind: 'file',
        doc_type: null,
        doc_id: null,
        size_bytes: 1284500,
        needs_import: true,
        source_path: '/home/fz/Downloads/检索策略与纳入排除标准.pdf',
      },
    ],
    total: 3,
  }),

  // ── Office ──
  ...createDemoOfficeAndSystemHandlers(),
};

export interface DemoInvokeResult {
  hit: boolean;
  value?: unknown;
}

/** 中央通道查表: 命中返回 {hit:true, value}, 未命中 {hit:false} 走原通道. */
export function demoInvoke(cmd: string, args: Record<string, unknown>): DemoInvokeResult {
  const handler = demoHandlers[cmd];
  if (!handler) return { hit: false };
  return { hit: true, value: handler(args) };
}

export function searchDemoMemories(query: string, memoryType?: 'episodic' | 'semantic'): Memory[] {
  const lower = query.toLowerCase();
  return demoMemories.filter((m) => {
    if (memoryType && m.memory_type && m.memory_type !== memoryType) return false;
    return (
      m.content.toLowerCase().includes(lower) ||
      (m.summary?.toLowerCase().includes(lower) ?? false) ||
      m.tags.some((t) => t.toLowerCase().includes(lower))
    );
  });
}

/** 聊天脚本结束后把用户消息 + 助手回复写入会话历史 (含计数/时间/标题). */
export function demoAppendMessages(
  sessionId: string,
  userMessage: string,
  assistantContent: string,
): void {
  const list = demoMessages.get(sessionId) ?? [];
  const nowMs = Date.now();
  const userMessageItem: Message = {
    id: demoUUID(),
    session_id: sessionId,
    role: 'user',
    content: userMessage,
    created_at: nowMs,
  };
  const assistantMessageItem: Message = {
    id: demoUUID(),
    session_id: sessionId,
    role: 'assistant',
    content: assistantContent,
    created_at: nowMs + 1,
    model: 'qwen2.5-72b-instruct',
  };
  demoMessages.set(sessionId, [...list, userMessageItem, assistantMessageItem]);
  const session = demoSessions.find((s) => s.id === sessionId);
  if (session) {
    session.message_count = (session.message_count ?? 0) + 2;
    session.last_message_at = nowMs;
    session.updated_at = nowMs;
    if (session.title === '新会话') {
      session.title = userMessage.slice(0, 24) || '新会话';
    }
  }
}
