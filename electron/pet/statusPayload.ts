/**
 * Read-only status payload for the opt-in local HTTP API.
 *
 * Pure mapping so the HTTP server stays a thin transport. It mirrors the
 * same-user information the on-screen panel shows (session/task titles
 * included) and deliberately omits raw task error strings, which can contain
 * paths/commands. The trust boundary is the same OS user, gated by the
 * opt-in switch + bearer token.
 */
import type { PetConfig, PetSnapshot } from './types';

const MAX_SESSIONS = 5;
const MAX_TASKS = 10;

export interface PetStatusPayload {
  version: 1;
  updatedAt: number;
  action: string;
  detail: string | null;
  sessionId: string | null;
  sessionTitle: string | null;
  toolName: string | null;
  bubbleKey: string | null;
  todo: { done: number; total: number; active: string | null };
  progressKind: 'todo' | 'plan' | null;
  context: { used: number | null; max: number | null };
  lastTerminal: { action: 'done' | 'error'; at: number | null } | null;
  companion: { bondDays: number; patCount: number };
  activeSessions: number;
  sessions: Array<{
    sessionId: string;
    sessionTitle: string | null;
    action: string;
    detail: string | null;
    toolName: string | null;
    todoDone: number;
    todoTotal: number;
    updatedAt: number;
  }>;
  tasks: Array<{
    id: string;
    kind: string;
    title: string;
    status: string;
    percent: number | null;
    sessionId: string | null;
  }>;
  pets: Array<{ id: string; petPack: string; size: string }>;
  config: {
    enabled: boolean;
    displayMode: string;
    tempo: string;
    bubbleMode: string;
    reduceMotion: boolean;
    compatibilityMode: string;
    externalApi: boolean;
  };
}

export function buildStatusPayload(
  snapshot: PetSnapshot,
  config: PetConfig,
): PetStatusPayload {
  return {
    version: 1,
    updatedAt: snapshot.updatedAt,
    action: snapshot.action,
    detail: snapshot.detail,
    sessionId: snapshot.sessionId,
    sessionTitle: snapshot.sessionTitle,
    toolName: snapshot.toolName,
    bubbleKey: snapshot.bubbleKey,
    todo: {
      done: snapshot.todoDone,
      total: snapshot.todoTotal,
      active: snapshot.todoActive,
    },
    progressKind: snapshot.progressKind,
    context: { used: snapshot.contextUsed, max: snapshot.contextMax },
    lastTerminal: snapshot.lastTerminalAction
      ? { action: snapshot.lastTerminalAction, at: snapshot.lastTerminalAt }
      : null,
    companion: { bondDays: snapshot.bondDays, patCount: snapshot.patCount },
    activeSessions: snapshot.activeSessions,
    sessions: snapshot.sessions.slice(0, MAX_SESSIONS).map((session) => ({
      sessionId: session.sessionId,
      sessionTitle: session.sessionTitle,
      action: session.action,
      detail: session.detail,
      toolName: session.toolName,
      todoDone: session.todoDone,
      todoTotal: session.todoTotal,
      updatedAt: session.updatedAt,
    })),
    tasks: snapshot.tasks.slice(0, MAX_TASKS).map((task) => ({
      id: task.id,
      kind: task.kind,
      title: task.title,
      status: task.status,
      percent: task.percent ?? null,
      sessionId: task.sessionId ?? null,
    })),
    pets: config.pets.map((pet) => ({ id: pet.id, petPack: pet.petPack, size: pet.size })),
    config: {
      enabled: config.enabled,
      displayMode: config.displayMode,
      tempo: config.tempo,
      bubbleMode: config.bubbleMode,
      reduceMotion: config.reduceMotion,
      compatibilityMode: config.compatibilityMode,
      externalApi: config.externalApi,
    },
  };
}
