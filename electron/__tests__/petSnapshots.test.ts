import { describe, expect, it } from 'vitest';

import { buildSnapshotBundle } from '../pet/snapshots';
import type { PetConfig } from '../pet/types';
import type { PetSessionState } from '../pet/state';

const T0 = 1_000_000;

function session(action: PetSessionState[string]['action'], updatedAt = T0) {
  return {
    action,
    detail: null,
    toolName: null,
    bubbleKey: null,
    bubbleKind: null,
    priority: 0,
    updatedAt,
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

const config: PetConfig = {
  version: 3,
  enabled: true,
  displayMode: 'desktop',
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
    { id: 'pet-2', petPack: 'dafeiyu', size: 'small', followMode: 'pinned', pinnedSessionId: 'b' },
  ],
};

describe('buildSnapshotBundle', () => {
  it('gives each pet its own Activity while sharing global Attention', () => {
    const sessions: PetSessionState = {
      a: session('acting', T0 + 1),
      b: session('waiting', T0 + 2),
    };
    const bundle = buildSnapshotBundle({
      sessions,
      tasks: [],
      config,
      focusSessionId: 'a',
      profile: { version: 1, firstSeenAt: T0, patCount: 4, lastPatAt: null },
      now: T0 + 10,
    });

    expect(bundle.global.action).toBe('waiting');
    expect(bundle.global.sessionId).toBe('b');
    expect(bundle.global.attention).toMatchObject({ needsYou: 1, running: 1, total: 2 });
    expect(bundle.byPet.default).toMatchObject({ action: 'acting', sessionId: 'a' });
    expect(bundle.byPet['pet-2']).toMatchObject({ action: 'waiting', sessionId: 'b' });
    expect(bundle.byPet.default?.patCount).toBe(4);
  });

  it('applies task overrides and bubble mode per pet', () => {
    const bundle = buildSnapshotBundle({
      sessions: { a: session('thinking') },
      tasks: [
        {
          id: 'task-1',
          kind: 'scheduled',
          title: '备份',
          status: 'awaiting_approval',
          sessionId: 'task-session',
        },
      ],
      config: { ...config, bubbleMode: 'off' },
      focusSessionId: null,
      profile: { version: 1, firstSeenAt: T0, patCount: 0, lastPatAt: null },
      now: T0,
    });
    // Task override only applies when the followed session is idle, so the
    // active session still wins; attention still surfaces the approval.
    expect(bundle.global.attention.needsYou).toBe(1);
    expect(bundle.global.bubbleKey).toBeNull();
    expect(bundle.byPet.default?.bubbleKey).toBeNull();
  });
});
