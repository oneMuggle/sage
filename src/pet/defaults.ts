/**
 * Shared renderer defaults for the pet overlay and the standalone panel
 * window (both subscribe to the same snapshot/config bridge).
 */
import type { PetConfigBridge, PetSnapshotBridge } from '../shared/types/electron-api';

const isWindows =
  typeof process !== 'undefined' && process.platform === 'win32';

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
  attention: {
    needsYou: 0,
    failed: 0,
    running: 0,
    activeTasks: 0,
    total: 0,
    needsYouSessionIds: [],
  },
  sessions: [],
  tasks: [],
  updatedAt: 0,
};

export const DEFAULT_CONFIG: PetConfigBridge = {
  version: 3,
  enabled: true,
  displayMode: isWindows ? 'in-app' : 'desktop',
  tempo: 'standard',
  reduceMotion: false,
  bubbleMode: 'important',
  soundScenes: { waiting: true, error: false, done: false },
  showSessionTitle: false,
  compatibilityMode: 'auto',
  externalApi: false,
  pets: [
    {
      id: 'default',
      petPack: 'dafeiyu',
      size: 'medium',
      followMode: 'focus',
      pinnedSessionId: null,
    },
  ],
  petId: 'default',
  petPack: 'dafeiyu',
  size: 'medium',
  followMode: 'focus',
  pinnedSessionId: null,
};
