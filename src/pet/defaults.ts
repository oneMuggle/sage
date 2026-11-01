/**
 * Shared renderer defaults for the pet overlay and the standalone panel
 * window (both subscribe to the same snapshot/config bridge).
 */
import type { PetConfigBridge, PetSnapshotBridge } from '../shared/types/electron-api';

export const EMPTY_SNAPSHOT: PetSnapshotBridge = {
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
  tasks: [],
  updatedAt: 0,
};

export const DEFAULT_CONFIG: PetConfigBridge = {
  version: 2,
  enabled: true,
  displayMode: 'desktop',
  tempo: 'standard',
  reduceMotion: false,
  bubbleMode: 'important',
  soundScenes: { waiting: true, error: false, done: false },
  showSessionTitle: false,
  compatibilityMode: 'auto',
  followActiveSession: true,
  externalApi: false,
  pets: [{ id: 'default', petPack: 'dafeiyu', size: 'medium' }],
  petId: 'default',
  petPack: 'dafeiyu',
  size: 'medium',
};
