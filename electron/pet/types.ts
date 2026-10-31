/**
 * Shared pet types for the main process and the pet renderer.
 *
 * The action names are Sage's semantic vocabulary; the renderer maps them to
 * animation assets from the selected pet pack.
 */

export type PetAction =
  | 'idle'
  | 'sleeping'
  | 'thinking'
  | 'acting'
  | 'waiting'
  | 'retry'
  | 'done'
  | 'error'
  | 'observing';

export type PetDetail = 'bash' | 'edit' | 'read' | 'web' | 'mcp' | 'office' | 'other';

export type PetBubbleKey =
  | 'waiting'
  | 'error'
  | 'done'
  | 'retry'
  | 'tool_bash'
  | 'tool_edit'
  | 'tool_read'
  | 'tool_web'
  | 'tool_mcp'
  | 'tool_office'
  | 'tool_other'
  | 'subagent'
  | 'todo'
  | 'progress';

export type PetBubbleKind = 'info' | 'success' | 'error' | 'waiting';

export type PetProgressKind = 'todo' | 'plan';

export type PetSize = 'mini' | 'small' | 'medium' | 'large' | 'huge';
export type PetTempo = 'quiet' | 'standard' | 'lively';
export type PetDisplayMode = 'desktop' | 'in-app' | 'both' | 'off';
export type PetBubbleMode = 'important' | 'always' | 'off';
export type PetCompatibilityMode = 'auto' | 'on' | 'off';

export interface PetSoundScenes {
  waiting: boolean;
  error: boolean;
  done: boolean;
}

/** One desktop pet instance. Global behavior settings live on PetConfig. */
export interface PetInstanceConfig {
  /** Stable id; also names the window-position file. */
  id: string;
  petPack: string;
  size: PetSize;
}

export interface PetConfig {
  version: 2;
  enabled: boolean;
  displayMode: PetDisplayMode;
  tempo: PetTempo;
  reduceMotion: boolean;
  bubbleMode: PetBubbleMode;
  soundScenes: PetSoundScenes;
  showSessionTitle: boolean;
  compatibilityMode: PetCompatibilityMode;
  followActiveSession: boolean;
  /** 1–3 pets, each with its own pack and size. */
  pets: PetInstanceConfig[];
}

/**
 * Per-window view of PetConfig: globals plus this instance's identity, pack
 * and size. The renderer only needs `petId` / `petPack` / `size` from this.
 */
export interface PetRenderConfig extends PetConfig {
  petId: string;
  petPack: string;
  size: PetSize;
}

/**
 * Normalized user pack manifest (validated from `userData/pets/<id>/pack.json`).
 * Built-in packs live in the renderer bundle and never pass through here.
 */
export interface PetPackManifest {
  id: string;
  name: string;
  version: string;
  license: string;
  source?: string;
  canvas: { width: number; height: number };
  anchor: { x: number; y: number };
  actions: Record<string, string[]>;
}

export type PetTaskStatus =
  | 'queued'
  | 'running'
  | 'awaiting_approval'
  | 'paused'
  | 'succeeded'
  | 'failed'
  | 'cancelled';

/** A Task Center entry reported by the main window renderer. */
export interface PetTaskReport {
  id: string;
  kind: string;
  title: string;
  status: PetTaskStatus;
  phase?: string | null;
  percent?: number | null;
  sessionId?: string | null;
  runId?: string | null;
  error?: string | null;
  startedAt?: number | null;
  finishedAt?: number | null;
}

export type PetTaskSummary = PetTaskReport;

/** One active/recent session row shown in the pet panel. */
export interface PetSessionSummary {
  sessionId: string;
  sessionTitle: string | null;
  action: PetAction;
  detail: PetDetail | null;
  toolName: string | null;
  bubbleKey: PetBubbleKey | null;
  todoDone: number;
  todoTotal: number;
  todoActive: string | null;
  progressKind: PetProgressKind | null;
  contextUsed: number | null;
  contextMax: number | null;
  lastTerminalAction: 'done' | 'error' | null;
  lastTerminalAt: number | null;
  updatedAt: number;
}

export interface PetSnapshot {
  action: PetAction;
  detail: PetDetail | null;
  sessionId: string | null;
  sessionTitle: string | null;
  toolName: string | null;
  bubbleKey: PetBubbleKey | null;
  bubbleKind: PetBubbleKind | null;
  todoDone: number;
  todoTotal: number;
  todoActive: string | null;
  progressKind: PetProgressKind | null;
  contextUsed: number | null;
  contextMax: number | null;
  lastTerminalAction: 'done' | 'error' | null;
  lastTerminalAt: number | null;
  /** Companion stats (filled by the controller from pet-profile.json). */
  patCount: number;
  bondDays: number;
  activeSessions: number;
  /** Active/recent sessions, highest priority first (panel only). */
  sessions: PetSessionSummary[];
  /** Background tasks reported by the main window Task Center. */
  tasks: PetTaskSummary[];
  updatedAt: number;
}

/** Metadata refreshed outside the event stream (title / token usage). */
export interface PetSessionMeta {
  sessionTitle?: string | null;
  contextUsed?: number | null;
  contextMax?: number | null;
}
