import { app } from 'electron';
import * as fs from 'fs/promises';
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
  } | null;
  lastRecordedVersion: string;
  postInstallMarker?: {
    version: string;
    installedAt: string;
  } | null;
}

const STATE_FILE = 'update-state.json';
const HMAC_SECRET_ENV = 'SAGE_UPDATE_STATE_HMAC_SECRET';

export class StateManager {
  private statePath: string;
  private hmacSecret: string;

  constructor() {
    this.statePath = path.join(app.getPath('userData'), STATE_FILE);
    this.hmacSecret = process.env[HMAC_SECRET_ENV] || 'default-dev-secret-change-in-prod';
  }

  async getState(): Promise<UpdateState> {
    try {
      const data = await fs.readFile(this.statePath, 'utf-8');
      const parsed = JSON.parse(data);

      // Verify HMAC integrity
      const { hmac, ...state } = parsed;
      const expectedHmac = this.computeHmac(JSON.stringify(state));
      if (hmac !== expectedHmac) {
        console.warn('Update state HMAC mismatch, resetting to defaults');
        return this.getDefaultState();
      }

      return state as UpdateState;
    } catch {
      // File doesn't exist or is corrupted, return defaults
      return this.getDefaultState();
    }
  }

  async setState(state: UpdateState): Promise<void> {
    const stateJson = JSON.stringify(state);
    const hmac = this.computeHmac(stateJson);
    const data = JSON.stringify({ ...state, hmac });

    await fs.writeFile(this.statePath, data, 'utf-8');
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
    };
  }

  private computeHmac(data: string): string {
    return crypto.createHmac('sha256', this.hmacSecret).update(data).digest('hex');
  }
}
