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
  | 'todo';

export type PetBubbleKind = 'info' | 'success' | 'error' | 'waiting';

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

export interface PetSnapshot {
  action: PetAction;
  detail: PetDetail | null;
  sessionId: string | null;
  sessionTitle: string | null;
  bubbleKey: PetBubbleKey | null;
  bubbleKind: PetBubbleKind | null;
  activeSessions: number;
  updatedAt: number;
}
