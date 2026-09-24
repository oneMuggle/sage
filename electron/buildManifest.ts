import { createHmac } from 'node:crypto';
import { readFileSync } from 'node:fs';

/** Versioned build/capability provenance shared by the Electron boundary. */

export const BUILD_MANIFEST_VERSION = 1;

/**
 * Which packaging pipeline produced this build.
 *
 * - "source":  backend Python + sage_core shipped as plain .py (reliable fallback)
 * - "cython":  backend .pyc + sage_core compiled to .pyd (experimental, source-protected)
 * - "unknown": legacy build before this field existed (alpha.54 and earlier)
 *
 * Added 2026-09-24 by the dual-build pipeline; field is optional so older
 * manifests still load via loadBuildManifest() with the default "unknown".
 */
export type PackagingMode = 'source' | 'cython' | 'unknown';

export interface BuildManifest {
  manifestVersion: number;
  buildId: string;
  commit: string;
  branch: string;
  version: string;
  electronVersion: string;
  pythonVersion: string;
  packagingMode?: PackagingMode;
}

export interface BuildManifestInputs {
  buildId?: string;
  commit?: string;
  branch?: string;
  version?: string;
  electronVersion?: string;
  pythonVersion?: string;
  packagingMode?: PackagingMode;
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
    packagingMode: inputs.packagingMode ?? 'unknown',
  };
}

function isPackagingMode(v: unknown): v is PackagingMode {
  return v === 'source' || v === 'cython' || v === 'unknown';
}

export function loadBuildManifest(path: string, fallback: BuildManifestInputs = {}): BuildManifest {
  try {
    const parsed: unknown = JSON.parse(readFileSync(path, 'utf8'));
    if (typeof parsed !== 'object' || parsed === null) return createBuildManifest(fallback);
    const value = parsed as Partial<BuildManifest>;
    if (value.manifestVersion !== BUILD_MANIFEST_VERSION) return createBuildManifest(fallback);
    const required = [
      value.buildId,
      value.commit,
      value.branch,
      value.version,
      value.electronVersion,
      value.pythonVersion,
    ];
    if (!required.every((item): item is string => typeof item === 'string' && item.length > 0)) {
      return createBuildManifest(fallback);
    }
    // After the type-guard above, every required field is `string`; the casts
    // below are the only way to teach TS about that narrowing inside an array
    // literal. Runtime correctness is enforced by the guard.
    const base: BuildManifest = {
      manifestVersion: BUILD_MANIFEST_VERSION,
      buildId: required[0] as string,
      commit: required[1] as string,
      branch: required[2] as string,
      version: required[3] as string,
      electronVersion: required[4] as string,
      pythonVersion: required[5] as string,
    };
    // packagingMode is optional for backwards-compat with alpha.54 and earlier.
    if (isPackagingMode(value.packagingMode)) {
      base.packagingMode = value.packagingMode;
    }
    return base;
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
  health: Partial<BackendHealthEnvelope> | null,
  ownership: BackendOwnership,
  manifest: BuildManifest,
): health is BackendHealthEnvelope {
  return (
    health != null &&
    health.status === 'ok' &&
    typeof health.proof === 'string' &&
    health.proof ===
      expectedHealthProof(
        ownership.ownershipToken,
        manifest.buildId,
        ownership.generation,
        ownership.pid,
      ) &&
    health.pid === ownership.pid &&
    health.generation === ownership.generation &&
    health.buildId === manifest.buildId
  );
}
