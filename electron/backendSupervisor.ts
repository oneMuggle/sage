import { randomUUID } from 'node:crypto';

export interface BackendGeneration {
  generation: number;
  pid: number;
  ownershipToken: string;
}

export type BackendLifecycle = 'idle' | 'starting' | 'ready' | 'stopping';

export interface BackendSupervisorState {
  lifecycle: BackendLifecycle;
  current: BackendGeneration | null;
}

export function createBackendGeneration(generation: number, pid: number): BackendGeneration {
  return { generation, pid, ownershipToken: randomUUID() };
}

export function isCurrentGeneration(
  candidate: Partial<BackendGeneration> | null | undefined,
  current: BackendGeneration | null,
): boolean {
  return Boolean(
    candidate &&
      current &&
      candidate.generation === current.generation &&
      candidate.pid === current.pid &&
      candidate.ownershipToken === current.ownershipToken,
  );
}

export function canStartBackend(state: BackendSupervisorState): boolean {
  return state.lifecycle === 'idle' && state.current === null;
}

export function transitionBackend(
  state: BackendSupervisorState,
  lifecycle: BackendLifecycle,
  current: BackendGeneration | null = state.current,
): BackendSupervisorState {
  return { lifecycle, current };
}
