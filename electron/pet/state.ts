/**
 * Pure Agent-state → pet-action reducer.
 *
 * Kept free of Electron/HTTP imports so it can be unit-tested and replayed.
 * The controller feeds normalized NDJSON AgentEvents in; the renderer only
 * sees the selected PetSnapshot.
 */

import type {
  PetAction,
  PetBubbleKey,
  PetBubbleKind,
  PetDetail,
  PetProgressKind,
  PetSessionMeta,
  PetSessionSummary,
  PetSnapshot,
} from './types';

export interface PetTodoItem {
  content?: string;
  status?: string;
  activeForm?: string;
}

export interface PetAgentEvent {
  state?: string;
  status?: string;
  error?: string;
  tool_call?: {
    function?: { name?: string };
  };
  todos?: PetTodoItem[];
  total?: number;
  done?: number;
  running?: number;
  failed?: number;
}

export interface SessionPetState {
  action: PetAction;
  detail: PetDetail | null;
  toolName: string | null;
  bubbleKey: PetBubbleKey | null;
  bubbleKind: PetBubbleKind | null;
  priority: number;
  updatedAt: number;
  terminalAt: number | null;
  sessionTitle: string | null;
  todoDone: number;
  todoTotal: number;
  todoActive: string | null;
  progressKind: PetProgressKind | null;
  contextUsed: number | null;
  contextMax: number | null;
  lastTerminalAction: 'done' | 'error' | null;
  lastTerminalAt: number | null;
}

export type PetSessionState = Record<string, SessionPetState>;

export const ACTION_PRIORITY: Record<PetAction, number> = {
  waiting: 100,
  error: 90,
  // Terminal completion must not mask active work in another session:
  // thinking/acting/retry stay above done so the pet keeps showing "running".
  thinking: 40,
  acting: 60,
  retry: 50,
  done: 35,
  observing: 30,
  idle: 0,
  sleeping: 0,
};

const TERMINAL_DECAY_MS = 45_000;
const SLEEP_AFTER_MS = 120_000;
const SESSION_TTL_MS = 10 * 60_000;
const PANEL_SESSION_LIMIT = 5;
const ACTIVE_ACTIONS = new Set<PetAction>(['thinking', 'acting', 'waiting', 'retry', 'observing']);

interface Step {
  action: PetAction;
  detail: PetDetail | null;
  toolName: string | null;
  bubbleKey: PetBubbleKey | null;
  bubbleKind: PetBubbleKind | null;
  preserveAction?: boolean;
  todoDone?: number;
  todoTotal?: number;
  todoActive?: string | null;
  progressKind?: PetProgressKind;
}

function baseState(now: number): SessionPetState {
  return {
    action: 'idle',
    detail: null,
    toolName: null,
    bubbleKey: null,
    bubbleKind: null,
    priority: 0,
    updatedAt: now,
    terminalAt: null,
    sessionTitle: null,
    todoDone: 0,
    todoTotal: 0,
    todoActive: null,
    progressKind: null,
    contextUsed: null,
    contextMax: null,
    lastTerminalAction: null,
    lastTerminalAt: null,
  };
}

export function createEmptyState(): PetSessionState {
  return {};
}

export function classifyTool(name: string | undefined): PetDetail {
  if (!name) return 'other';
  const n = name.toLowerCase();
  if (n.startsWith('mcp__') || n.includes('mcp')) return 'mcp';
  if (
    n.startsWith('office_') ||
    n.includes('docx') ||
    n.includes('xlsx') ||
    n.includes('pptx') ||
    n === 'word' ||
    n === 'excel'
  ) {
    return 'office';
  }
  if (n === 'bash' || n.includes('shell') || n.includes('terminal') || n.includes('run_command')) {
    return 'bash';
  }
  if (n.includes('web') || n.includes('fetch') || n.includes('browse') || n.includes('http')) {
    return 'web';
  }
  if (n.includes('edit') || n.includes('write') || n.includes('patch') || n.includes('apply')) {
    return 'edit';
  }
  if (
    n.includes('read') ||
    n.includes('grep') ||
    n.includes('glob') ||
    n.includes('search_files') ||
    n.includes('list_dir')
  ) {
    return 'read';
  }
  return 'other';
}

function toolStep(detail: PetDetail, toolName: string | null): Step {
  return {
    action: 'acting',
    detail,
    toolName,
    bubbleKey: `tool_${detail}` as PetBubbleKey,
    bubbleKind: 'info',
  };
}

function todoStep(event: PetAgentEvent): Step | null {
  const todos = Array.isArray(event.todos) ? event.todos : [];
  if (todos.length === 0) return null;
  const done = todos.filter((item) => item.status === 'completed').length;
  const active =
    todos.find((item) => item.status === 'in_progress') ??
    todos.find((item) => item.status === 'pending');
  return {
    action: 'thinking',
    detail: null,
    toolName: null,
    bubbleKey: 'todo',
    bubbleKind: 'info',
    preserveAction: true,
    todoDone: done,
    todoTotal: todos.length,
    todoActive: active ? active.activeForm || active.content || null : null,
    progressKind: 'todo',
  };
}

function progressStep(event: PetAgentEvent): Step | null {
  const total = typeof event.total === 'number' ? event.total : 0;
  if (total <= 0) return null;
  const done = typeof event.done === 'number' ? event.done : 0;
  return {
    action: 'thinking',
    detail: null,
    toolName: null,
    bubbleKey: 'progress',
    bubbleKind: 'info',
    preserveAction: true,
    todoDone: Math.min(done, total),
    todoTotal: total,
    todoActive: null,
    progressKind: 'plan',
  };
}

function stepForEvent(event: PetAgentEvent): Step | null {
  const state = event.state ?? '';
  switch (state) {
    case 'permission_request':
    case 'ask_user_question':
    case 'awaiting_step_confirm':
    case 'approval_mode':
      return {
        action: 'waiting',
        detail: null,
        toolName: null,
        bubbleKey: 'waiting',
        bubbleKind: 'waiting',
      };
    case 'failed':
      return {
        action: 'error',
        detail: null,
        toolName: null,
        bubbleKey: 'error',
        bubbleKind: 'error',
      };
    case 'done':
      return {
        action: 'done',
        detail: null,
        toolName: null,
        bubbleKey: 'done',
        bubbleKind: 'success',
      };
    case 'acting':
      return toolStep(
        classifyTool(event.tool_call?.function?.name),
        event.tool_call?.function?.name ?? null,
      );
    case 'retry':
      return {
        action: 'retry',
        detail: null,
        toolName: null,
        bubbleKey: 'retry',
        bubbleKind: 'info',
      };
    case 'thinking':
    case 'reasoning':
    case 'reasoning_delta':
    case 'reasoning_final':
    case 'content_delta':
      return {
        action: 'thinking',
        detail: null,
        toolName: null,
        bubbleKey: null,
        bubbleKind: null,
      };
    case 'observing':
    case 'step_done':
      return {
        action: 'observing',
        detail: null,
        toolName: null,
        bubbleKey: null,
        bubbleKind: null,
      };
    case 'subagent_event':
      return {
        action: 'acting',
        detail: 'other',
        toolName: null,
        bubbleKey: 'subagent',
        bubbleKind: 'info',
      };
    case 'task_status':
      if (event.status === 'failed') {
        return {
          action: 'error',
          detail: null,
          toolName: null,
          bubbleKey: 'error',
          bubbleKind: 'error',
        };
      }
      if (event.status === 'running') {
        return toolStep('other', null);
      }
      return null;
    case 'todo_snapshot':
      return todoStep(event);
    case 'task_progress':
      return progressStep(event);
    case 'idle':
      return {
        action: 'idle',
        detail: null,
        toolName: null,
        bubbleKey: null,
        bubbleKind: null,
      };
    case 'heartbeat':
    case 'task_plan':
    case 'task_review':
    case 'topic_shifted':
      return null;
    default:
      return null;
  }
}

/**
 * Apply one AgentEvent for a session. Returns a new map (never mutates input).
 * Unknown/heartbeat events only refresh `updatedAt` so a long Retry backoff
 * does not make the pet fall asleep.
 */
export function applyEvent(
  state: PetSessionState,
  sessionId: string,
  event: PetAgentEvent,
  now: number,
): PetSessionState {
  const previous = state[sessionId] ?? baseState(now);
  const step = stepForEvent(event);
  if (step === null) {
    return {
      ...state,
      [sessionId]: { ...previous, updatedAt: now },
    };
  }
  const preserve =
    step.preserveAction === true && previous.action !== 'idle' && previous.action !== 'sleeping';
  const action = preserve ? previous.action : step.action;
  const terminal = action === 'done' || action === 'error';
  // A todo/progress event must not replace a more urgent bubble (waiting or
  // an active tool) — it only updates the progress fields.
  const keepBubble =
    preserve && previous.priority > ACTION_PRIORITY.thinking && previous.bubbleKey !== null;
  const todoDone =
    action === 'done' && previous.progressKind === 'plan' && previous.todoTotal > 0
      ? previous.todoTotal
      : (step.todoDone ?? previous.todoDone);
  return {
    ...state,
    [sessionId]: {
      ...previous,
      action,
      detail: preserve ? previous.detail : step.detail,
      toolName: step.toolName ?? previous.toolName,
      bubbleKey: keepBubble ? previous.bubbleKey : step.bubbleKey,
      bubbleKind: keepBubble ? previous.bubbleKind : step.bubbleKind,
      priority: preserve ? previous.priority : ACTION_PRIORITY[action],
      updatedAt: now,
      terminalAt: terminal ? (preserve ? (previous.terminalAt ?? now) : now) : null,
      todoDone,
      todoTotal: step.todoTotal ?? previous.todoTotal,
      todoActive: step.todoActive !== undefined ? step.todoActive : previous.todoActive,
      progressKind: step.progressKind ?? previous.progressKind,
      lastTerminalAction: terminal
        ? ((preserve ? (previous.lastTerminalAction ?? action) : action) as 'done' | 'error')
        : previous.lastTerminalAction,
      lastTerminalAt: terminal
        ? preserve
          ? (previous.lastTerminalAt ?? now)
          : now
        : previous.lastTerminalAt,
    },
  };
}

/** Merge title/token metadata fetched outside the event stream. */
export function applyMeta(
  state: PetSessionState,
  sessionId: string,
  meta: PetSessionMeta,
  now: number,
): PetSessionState {
  const previous = state[sessionId] ?? baseState(now);
  return {
    ...state,
    [sessionId]: {
      ...previous,
      sessionTitle: meta.sessionTitle !== undefined ? meta.sessionTitle : previous.sessionTitle,
      contextUsed: meta.contextUsed !== undefined ? meta.contextUsed : previous.contextUsed,
      contextMax: meta.contextMax !== undefined ? meta.contextMax : previous.contextMax,
    },
  };
}

/**
 * Time-based transitions: terminal actions decay to idle after 45s (the last
 * terminal result is retained for the panel); idle sessions fall asleep after
 * 2 minutes; stale idle sessions are dropped.
 */
export function tick(state: PetSessionState, now: number): PetSessionState {
  let changed = false;
  const next: PetSessionState = {};
  for (const [sessionId, session] of Object.entries(state)) {
    let current = session;
    if (current.terminalAt !== null && now - current.terminalAt >= TERMINAL_DECAY_MS) {
      current = {
        ...current,
        action: 'idle',
        detail: null,
        bubbleKey: null,
        bubbleKind: null,
        priority: 0,
        updatedAt: current.terminalAt + TERMINAL_DECAY_MS,
        terminalAt: null,
      };
      changed = true;
    } else if (current.action === 'idle' && now - current.updatedAt >= SLEEP_AFTER_MS) {
      current = { ...current, action: 'sleeping', priority: 0 };
      changed = true;
    }
    if (
      (current.action === 'idle' || current.action === 'sleeping') &&
      now - current.updatedAt > SESSION_TTL_MS
    ) {
      changed = true;
      continue;
    }
    next[sessionId] = current;
  }
  return changed ? next : state;
}

function toSummary(sessionId: string, session: SessionPetState): PetSessionSummary {
  return {
    sessionId,
    sessionTitle: session.sessionTitle,
    action: session.action,
    detail: session.detail,
    toolName: session.toolName,
    bubbleKey: session.bubbleKey,
    todoDone: session.todoDone,
    todoTotal: session.todoTotal,
    todoActive: session.todoActive,
    progressKind: session.progressKind,
    contextUsed: session.contextUsed,
    contextMax: session.contextMax,
    lastTerminalAction: session.lastTerminalAction,
    lastTerminalAt: session.lastTerminalAt,
    updatedAt: session.updatedAt,
  };
}

function emptySnapshot(now: number): PetSnapshot {
  return {
    action: 'idle',
    detail: null,
    sessionId: null,
    sessionTitle: null,
    toolName: null,
    bubbleKey: null,
    bubbleKind: null,
    todoDone: 0,
    todoTotal: 0,
    todoActive: null,
    progressKind: null,
    contextUsed: null,
    contextMax: null,
    lastTerminalAction: null,
    lastTerminalAt: null,
    patCount: 0,
    bondDays: 1,
    activeSessions: 0,
    sessions: [],
    updatedAt: now,
  };
}

/**
 * Pick the highest-priority session; ties go to the most recently updated.
 * The snapshot also carries up to five sessions for the pet panel.
 */
export function selectSnapshot(state: PetSessionState, now: number): PetSnapshot {
  const sorted = Object.entries(state)
    .map(([sessionId, session]) => ({ sessionId, session }))
    .sort(
      (a, b) =>
        b.session.priority - a.session.priority || b.session.updatedAt - a.session.updatedAt,
    );
  if (sorted.length === 0) return emptySnapshot(now);
  const activeSessions = sorted.filter(({ session }) => ACTIVE_ACTIONS.has(session.action)).length;
  const sessions = sorted
    .slice(0, PANEL_SESSION_LIMIT)
    .map(({ sessionId, session }) => toSummary(sessionId, session));
  const best = sorted[0];
  const session = best.session;
  const selected =
    session.action === 'idle' || session.action === 'sleeping' ? null : best.sessionId;
  return {
    action: session.action,
    detail: session.detail,
    sessionId: selected,
    sessionTitle: session.sessionTitle,
    toolName: session.toolName,
    bubbleKey: session.bubbleKey,
    bubbleKind: session.bubbleKind,
    todoDone: session.todoDone,
    todoTotal: session.todoTotal,
    todoActive: session.todoActive,
    progressKind: session.progressKind,
    contextUsed: session.contextUsed,
    contextMax: session.contextMax,
    lastTerminalAction: session.lastTerminalAction,
    lastTerminalAt: session.lastTerminalAt,
    patCount: 0,
    bondDays: 1,
    activeSessions,
    sessions,
    updatedAt: session.updatedAt,
  };
}
