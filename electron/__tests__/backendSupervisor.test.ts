import { describe, expect, it } from 'vitest';
import {
  canStartBackend,
  createBackendGeneration,
  isCurrentGeneration,
  transitionBackend,
  type BackendSupervisorState,
} from '../backendSupervisor';
import { BUILD_MANIFEST_VERSION, createBuildManifest, expectedHealthProof, ownsBackend } from '../buildManifest';

describe('backend supervisor generation fencing', () => {
  it('creates unique ownership tokens for each generation', () => {
    const first = createBackendGeneration(1, 101);
    const second = createBackendGeneration(2, 202);

    expect(first).toMatchObject({ generation: 1, pid: 101 });
    expect(second).toMatchObject({ generation: 2, pid: 202 });
    expect(first.ownershipToken).not.toBe(second.ownershipToken);
  });

  it('accepts only an exact generation, pid, and token match', () => {
    const current = createBackendGeneration(3, 303);

    expect(isCurrentGeneration(current, current)).toBe(true);
    expect(isCurrentGeneration({ ...current, generation: 2 }, current)).toBe(false);
    expect(isCurrentGeneration({ ...current, pid: 404 }, current)).toBe(false);
    expect(isCurrentGeneration({ ...current, ownershipToken: 'stale' }, current)).toBe(false);
    expect(isCurrentGeneration(null, current)).toBe(false);
  });

  it('allows starts only from an idle state without an owned process', () => {
    const idle: BackendSupervisorState = { lifecycle: 'idle', current: null };
    expect(canStartBackend(idle)).toBe(true);
    expect(canStartBackend(transitionBackend(idle, 'starting', createBackendGeneration(1, 1)))).toBe(false);
    expect(canStartBackend({ lifecycle: 'ready', current: null })).toBe(false);
    expect(canStartBackend({ lifecycle: 'stopping', current: null })).toBe(false);
  });
});

describe('build manifest and health ownership', () => {
  it('keeps the manifest versioned and rejects stale health envelopes', () => {
    const manifest = createBuildManifest({
      buildId: 'build-1',
      commit: 'abc',
      branch: 'main',
      version: '1.2.3',
      electronVersion: '21.4.4',
      pythonVersion: '3.8.10',
    });
    const owner = createBackendGeneration(4, 404);
    const health = {
      status: 'ok' as const,
      ...manifest,
      ...owner,
      proof: expectedHealthProof(owner.ownershipToken, manifest.buildId, owner.generation, owner.pid),
    };

    expect(manifest.manifestVersion).toBe(BUILD_MANIFEST_VERSION);
    expect(ownsBackend(health, owner, manifest)).toBe(true);
    expect(ownsBackend({ ...health, pid: 405 }, owner, manifest)).toBe(false);
    expect(ownsBackend({ ...health, generation: 5 }, owner, manifest)).toBe(false);
    expect(ownsBackend({ ...health, buildId: 'other' }, owner, manifest)).toBe(false);
  });
});
