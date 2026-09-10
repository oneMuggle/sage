import { app } from 'electron';
import * as fs from 'fs/promises';
import * as fssync from 'fs';
import * as path from 'path';
import * as crypto from 'crypto';

export interface UpdateState {
  currentVersion: string;
  lastKnownGoodVersion: string;
  lastKnownGoodInstallDate: string; // ISO 8601
  crashCount: number;
  rollbackWindowDays: number;
  updateStrategy: 'manual' | 'auto-download' | 'auto-install';
  lastCheckTime: string | null; // ISO 8601
  updateAvailable?: boolean;
  availableUpdate?: {
    version: string;
    releaseNotes?: string;
  } | null;
  pendingUpdate: {
    version: string;
    downloadedAt: string; // ISO 8601
    releaseNotes?: string;
    fileUrl?: string;
    filename?: string;
    sha512?: string;
    size?: number;
    signature?: string;
  } | null;
  /** Metadata required to authenticate a cached installer before rollback. */
  cachedRollbackPackage?: {
    path: string;
    version: string;
    sha512: string;
    size: number;
    signature: string;
    fileUrl?: string;
  } | null;
  pendingInstallAttempt?: {
    version: string;
    previousVersion: string;
    startedAt: string;
    phase: 'prepared' | 'requested' | 'failed';
    pendingUpdate: NonNullable<UpdateState['pendingUpdate']>;
  } | null;
  lastRecordedVersion: string;
  postInstallMarker?: {
    version: string;
    installedAt: string;
  } | null;
}

const STATE_FILE = 'update-state.json';
const HMAC_SECRET_ENV = 'SAGE_UPDATE_STATE_HMAC_SECRET';

export function getUpdateHmacSecret(): string {
  const configuredSecret = process.env[HMAC_SECRET_ENV];
  if (configuredSecret) return configuredSecret;

  // Packaged and dev modes share the same per-installation fallback:
  // generate a 32-byte random secret on first launch and persist it to
  // userData (mode 0o600). Subsequent launches read the same secret.
  //
  // This used to throw "must be configured in packaged builds" when
  // SAGE_UPDATE_STATE_HMAC_SECRET was unset, but neither release.yml nor
  // release-win7.yml ever injects that env var — so every packaged build
  // shipped since PR #442/#447 crashed on first launch (alpha.18-win7 /
  // alpha.37-main all share this bug). The HMAC protects only the local
  // ``update-state.json`` integrity (it is not a cross-machine trust
  // anchor), so per-install random secrets are equivalent to a build-time
  // shared secret for this purpose. See PR #573 (alpha.20-win7).
  const secretPath = path.join(app.getPath('userData'), '.update-state-hmac-secret');
  try {
    return fssync.readFileSync(secretPath, 'utf8').trim();
  } catch {
    const generated = crypto.randomBytes(32).toString('hex');
    fssync.writeFileSync(secretPath, generated, { encoding: 'utf8', mode: 0o600 });
    return generated;
  }
}

export class StateManager {
  private statePath: string;
  private hmacSecret: string;

  constructor() {
    this.statePath = path.join(app.getPath('userData'), STATE_FILE);
    this.hmacSecret = getUpdateHmacSecret();
    if (this.hmacSecret.length < 32) {
      throw new Error(`${HMAC_SECRET_ENV} or a persistent development secret is invalid`);
    }
  }

  async getState(): Promise<UpdateState> {
    try {
      const data = await fs.readFile(this.statePath, 'utf-8');
      const parsed: unknown = JSON.parse(data);
      if (!this.isRecord(parsed) || typeof parsed.hmac !== 'string') {
        return this.getDefaultState();
      }

      // Verify HMAC integrity
      const { hmac, ...state } = parsed;
      const expectedHmac = this.computeHmac(JSON.stringify(state));
      if (!this.isValidState(state) || !this.safeEqual(hmac, expectedHmac)) {
        console.warn('Update state HMAC mismatch, resetting to defaults');
        return this.getDefaultState();
      }

      return state;
    } catch {
      // File doesn't exist or is corrupted, return defaults
      return this.getDefaultState();
    }
  }

  async setState(state: UpdateState): Promise<void> {
    const stateJson = JSON.stringify(state);
    const hmac = this.computeHmac(stateJson);
    const data = JSON.stringify({ ...state, hmac });
    const temporaryPath = `${this.statePath}.${process.pid}.tmp`;
    await fs.writeFile(temporaryPath, data, { encoding: 'utf-8', mode: 0o600 });
    await fs.rename(temporaryPath, this.statePath);
  }

  private getDefaultState(): UpdateState {
    const currentVersion = app.getVersion();
    return {
      currentVersion,
      lastKnownGoodVersion: currentVersion,
      lastKnownGoodInstallDate: new Date().toISOString(),
      crashCount: 0,
      rollbackWindowDays: 7,
      updateStrategy: 'auto-download',
      lastCheckTime: null,
      updateAvailable: false,
      availableUpdate: null,
      pendingUpdate: null,
      cachedRollbackPackage: null,
      lastRecordedVersion: currentVersion,
      postInstallMarker: null,
      pendingInstallAttempt: null,
    };
  }

  private isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value);
  }

  private isValidState(value: unknown): value is UpdateState {
    if (!this.isRecord(value)) return false;
    return (
      typeof value.currentVersion === 'string' &&
      typeof value.lastKnownGoodVersion === 'string' &&
      typeof value.lastKnownGoodInstallDate === 'string' &&
      Number.isInteger(value.crashCount) &&
      typeof value.rollbackWindowDays === 'number' &&
      ['manual', 'auto-download', 'auto-install'].includes(String(value.updateStrategy)) &&
      (value.lastCheckTime === null || typeof value.lastCheckTime === 'string') &&
      (value.pendingUpdate === null || this.isRecord(value.pendingUpdate)) &&
      (value.cachedRollbackPackage === null ||
        value.cachedRollbackPackage === undefined ||
        this.isRecord(value.cachedRollbackPackage)) &&
      typeof value.lastRecordedVersion === 'string'
    );
  }

  private safeEqual(actual: string, expected: string): boolean {
    const actualBuffer = Buffer.from(actual, 'utf8');
    const expectedBuffer = Buffer.from(expected, 'utf8');
    return (
      actualBuffer.length === expectedBuffer.length &&
      crypto.timingSafeEqual(actualBuffer, expectedBuffer)
    );
  }

  private computeHmac(data: string): string {
    return crypto.createHmac('sha256', this.hmacSecret).update(data).digest('hex');
  }
}
