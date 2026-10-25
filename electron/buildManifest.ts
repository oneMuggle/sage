import { createHmac } from 'node:crypto';
import { readFileSync } from 'node:fs';

/** Versioned build/capability provenance shared by the Electron boundary. */

export const BUILD_MANIFEST_VERSION = 1;

export interface BuildManifest {
  manifestVersion: number;
  buildId: string;
  commit: string;
  branch: string;
  version: string;
  electronVersion: string;
  pythonVersion: string;
}

export interface BuildManifestInputs {
  buildId?: string;
  commit?: string;
  branch?: string;
  version?: string;
  electronVersion?: string;
  pythonVersion?: string;
}

export function createBuildManifest(inputs: BuildManifestInputs = {}): BuildManifest {
  return {
    manifestVersion: BUILD_MANIFEST_VERSION,
    buildId: inputs.buildId ?? process.env.SAGE_BUILD_ID ?? 'dev-build',
    commit: inputs.commit ?? process.env.SAGE_BUILD_COMMIT ?? 'unknown',
    branch: inputs.branch ?? process.env.SAGE_BUILD_BRANCH ?? 'unknown',
    version: inputs.version ?? process.env.SAGE_BUILD_VERSION ?? 'unknown',
    electronVersion: inputs.electronVersion ?? process.versions.electron ?? 'unknown',
    pythonVersion: inputs.pythonVersion ?? process.env.SAGE_PYTHON_VERSION ?? 'unknown',
  };
}

export function loadBuildManifest(path: string, fallback: BuildManifestInputs = {}): BuildManifest {
  try {
    const parsed: unknown = JSON.parse(readFileSync(path, 'utf8'));
    if (typeof parsed !== 'object' || parsed === null) return createBuildManifest(fallback);
    const value = parsed as Partial<BuildManifest>;
    if (value.manifestVersion !== BUILD_MANIFEST_VERSION) return createBuildManifest(fallback);
    if (![value.buildId, value.commit, value.branch, value.version, value.electronVersion, value.pythonVersion].every((item) => typeof item === 'string' && item.length > 0)) {
      return createBuildManifest(fallback);
    }
    return value as BuildManifest;
  } catch {
    return createBuildManifest(fallback);
  }
}

export interface BackendOwnership {
  pid: number;
  generation: number;
  ownershipToken: string;
}

export interface BackendHealthEnvelope extends BuildManifest, BackendOwnership {
  status: 'ok';
  proof?: string;
}

export function expectedHealthProof(
  ownershipToken: string,
  buildId: string,
  generation: number,
  pid: number,
): string {
  return createHmac('sha256', ownershipToken)
    .update(`sage-health-v1:${buildId}:${generation}:${pid}`)
    .digest('hex');
}

export function ownsBackend(
  health: Partial<BackendHealthEnvelope>,
  ownership: BackendOwnership,
  manifest: BuildManifest,
): health is BackendHealthEnvelope {
  return (
    health.status === 'ok' &&
    typeof health.proof === 'string' &&
    health.proof === expectedHealthProof(ownership.ownershipToken, manifest.buildId, ownership.generation, ownership.pid) &&
    health.pid === ownership.pid &&
    health.generation === ownership.generation &&
    health.buildId === manifest.buildId
  );
}
