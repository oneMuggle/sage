/**
 * Pure Agent-state → pet-action reducer.
 *
 * Kept free of Electron/HTTP imports so it can be unit-tested and replayed.
 * The controller feeds normalized NDJSON AgentEvents in; the renderer only
 * sees the selected PetSnapshot.
 */

import type { PetAction, PetBubbleKey, PetBubbleKind, PetDetail, PetSnapshot } from './types';

export interface PetAgentEvent {
  state?: string;
  status?: string;
  error?: string;
  tool_call?: {
    function?: { name?: string };
  };
  todos?: unknown[];
}

export interface SessionPetState {
  action: PetAction;
  detail: PetDetail | null;
  bubbleKey: PetBubbleKey | null;
  bubbleKind: PetBubbleKind | null;
  priority: number;
  updatedAt: number;
  terminalAt: number | null;
}

export type PetSessionState = Record<string, SessionPetState>;

export const ACTION_PRIORITY: Record<PetAction, number> = {
  waiting: 100,
  error: 90,
  done: 80,
  acting: 60,
  retry: 50,
  thinking: 40,
  observing: 30,
  idle: 0,
  sleeping: 0,
};

const TERMINAL_DECAY_MS = 8_000;
const SLEEP_AFTER_MS = 120_000;
const SESSION_TTL_MS = 10 * 60_000;

interface Step {
  action: PetAction;
  detail: PetDetail | null;
  bubbleKey: PetBubbleKey | null;
  bubbleKind: PetBubbleKind | null;
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

function toolStep(detail: PetDetail): Step {
  return {
    action: 'acting',
    detail,
    bubbleKey: `tool_${detail}` as PetBubbleKey,
    bubbleKind: 'info',
  };
}

function stepForEvent(event: PetAgentEvent): Step | null {
  const state = event.state ?? '';
  switch (state) {
    case 'permission_request':
    case 'ask_user_question':
    case 'awaiting_step_confirm':
    case 'approval_mode':
      return { action: 'waiting', detail: null, bubbleKey: 'waiting', bubbleKind: 'waiting' };
    case 'failed':
      return { action: 'error', detail: null, bubbleKey: 'error', bubbleKind: 'error' };
    case 'done':
      return { action: 'done', detail: null, bubbleKey: 'done', bubbleKind: 'success' };
    case 'acting':
      return toolStep(classifyTool(event.tool_call?.function?.name));
    case 'retry':
      return { action: 'retry', detail: null, bubbleKey: 'retry', bubbleKind: 'info' };
    case 'thinking':
    case 'reasoning':
    case 'reasoning_delta':
    case 'reasoning_final':
    case 'content_delta':
      return { action: 'thinking', detail: null, bubbleKey: null, bubbleKind: null };
    case 'observing':
    case 'step_done':
      return { action: 'observing', detail: null, bubbleKey: null, bubbleKind: null };
    case 'subagent_event':
      return {
        action: 'acting',
        detail: 'other',
        bubbleKey: 'subagent',
        bubbleKind: 'info',
      };
    case 'task_status':
      if (event.status === 'failed') {
        return { action: 'error', detail: null, bubbleKey: 'error', bubbleKind: 'error' };
      }
      if (event.status === 'running') {
        return toolStep('other');
      }
      return null;
    case 'todo_snapshot':
      return {
        action: 'thinking',
        detail: null,
        bubbleKey: 'todo',
        bubbleKind: 'info',
      };
    case 'idle':
      return { action: 'idle', detail: null, bubbleKey: null, bubbleKind: null };
    case 'heartbeat':
    case 'task_plan':
    case 'task_progress':
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
  const previous = state[sessionId] ?? {
    action: 'idle' as PetAction,
    detail: null,
    bubbleKey: null,
    bubbleKind: null,
    priority: 0,
    updatedAt: now,
    terminalAt: null,
  };
  const step = stepForEvent(event);
  if (step === null) {
    return {
      ...state,
      [sessionId]: { ...previous, updatedAt: now },
    };
  }
  const terminal = step.action === 'done' || step.action === 'error';
  return {
    ...state,
    [sessionId]: {
      action: step.action,
      detail: step.detail,
      bubbleKey: step.bubbleKey,
      bubbleKind: step.bubbleKind,
      priority: ACTION_PRIORITY[step.action],
      updatedAt: now,
      terminalAt: terminal ? now : null,
    },
  };
}

/**
 * Time-based transitions: terminal actions decay to idle after 8s; idle
 * sessions fall asleep after 2 minutes; stale idle sessions are dropped.
 */
export function tick(state: PetSessionState, now: number): PetSessionState {
  let changed = false;
  const next: PetSessionState = {};
  for (const [sessionId, session] of Object.entries(state)) {
    let current = session;
    if (current.terminalAt !== null && now - current.terminalAt >= TERMINAL_DECAY_MS) {
      current = {
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

/**
 * Pick the highest-priority session; ties go to the most recently updated.
 * Returns an idle snapshot when nothing is active.
 */
export function selectSnapshot(state: PetSessionState, now: number): PetSnapshot {
  let best: { sessionId: string; session: SessionPetState } | null = null;
  let activeSessions = 0;
  for (const [sessionId, session] of Object.entries(state)) {
    if (session.action !== 'idle' && session.action !== 'sleeping') activeSessions += 1;
    if (
      best === null ||
      session.priority > best.session.priority ||
      (session.priority === best.session.priority && session.updatedAt >= best.session.updatedAt)
    ) {
      best = { sessionId, session };
    }
  }
  if (best === null) {
    return {
      action: 'idle',
      detail: null,
      sessionId: null,
      sessionTitle: null,
      bubbleKey: null,
      bubbleKind: null,
      activeSessions: 0,
      updatedAt: now,
    };
  }
  return {
    action: best.session.action,
    detail: best.session.detail,
    sessionId:
      best.session.action === 'idle' || best.session.action === 'sleeping' ? null : best.sessionId,
    sessionTitle: null,
    bubbleKey: best.session.bubbleKey,
    bubbleKind: best.session.bubbleKind,
    activeSessions,
    updatedAt: best.session.updatedAt,
  };
}
