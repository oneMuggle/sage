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

export interface PetConfig {
  version: 1;
  enabled: boolean;
  displayMode: PetDisplayMode;
  size: PetSize;
  tempo: PetTempo;
  reduceMotion: boolean;
  bubbleMode: PetBubbleMode;
  soundScenes: PetSoundScenes;
  showSessionTitle: boolean;
  compatibilityMode: PetCompatibilityMode;
  petPack: string;
  followActiveSession: boolean;
}

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
  activeSessions: number;
  /** Active/recent sessions, highest priority first (panel only). */
  sessions: PetSessionSummary[];
  updatedAt: number;
}

/** Metadata refreshed outside the event stream (title / token usage). */
export interface PetSessionMeta {
  sessionTitle?: string | null;
  contextUsed?: number | null;
  contextMax?: number | null;
}
