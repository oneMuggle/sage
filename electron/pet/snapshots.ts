/**
 * Build one global snapshot plus one snapshot per configured pet.
 *
 * The controller only dedupes and broadcasts; all composition lives here so
 * multi-session behavior is unit-testable without Electron.
 */

import { computeAttention, type PetFollowOptions } from './attention';
import { bondDays, type PetProfile } from './profile';
import { selectSnapshot, type PetSessionState } from './state';
import { applyTaskOverrides } from './tasks';
import type { PetBubbleMode, PetConfig, PetSnapshot, PetTaskReport } from './types';

export interface SnapshotBundleInput {
  sessions: PetSessionState;
  tasks: readonly PetTaskReport[];
  config: PetConfig;
  focusSessionId: string | null;
  profile: PetProfile;
  now: number;
}

export interface SnapshotBundle {
  global: PetSnapshot;
  byPet: Record<string, PetSnapshot>;
}

export function applyBubbleMode(snapshot: PetSnapshot, mode: PetBubbleMode): PetSnapshot {
  if (mode === 'off') return { ...snapshot, bubbleKey: null, bubbleKind: null };
  if (
    mode === 'important' &&
    snapshot.action !== 'waiting' &&
    snapshot.action !== 'error' &&
    snapshot.action !== 'done'
  ) {
    return { ...snapshot, bubbleKey: null, bubbleKind: null };
  }
  return snapshot;
}

export function buildSnapshotBundle(input: SnapshotBundleInput): SnapshotBundle {
  const { sessions, tasks, config, focusSessionId, profile, now } = input;
  const attention = computeAttention(sessions, tasks, now);
  const patCount = profile.patCount;
  const days = bondDays(profile, now);
  const taskList = [...tasks];

  const decorate = (base: PetSnapshot): PetSnapshot => {
    const withMeta = { ...base, patCount, bondDays: days, tasks: taskList };
    const overridden = applyTaskOverrides(withMeta, taskList, now);
    return applyBubbleMode(overridden, config.bubbleMode);
  };

  const global = decorate(selectSnapshot(sessions, now, { attention }));
  const byPet: Record<string, PetSnapshot> = {};
  for (const pet of config.pets) {
    const follow: PetFollowOptions = {
      mode: pet.followMode,
      focusSessionId,
      pinnedSessionId: pet.pinnedSessionId,
    };
    byPet[pet.id] = decorate(selectSnapshot(sessions, now, { follow, attention }));
  }
  return { global, byPet };
}
