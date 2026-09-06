import { app } from 'electron';
import * as fs from 'fs/promises';
import * as path from 'path';
import * as crypto from 'crypto';
import { getUpdateHmacSecret } from './updateState';

export type UpdateStrategy = 'manual' | 'auto-download' | 'auto-install';
export type UpdateChannel = 'stable' | 'beta' | 'alpha';

export interface UpdateConfig {
  updateStrategy: UpdateStrategy;
  channel: UpdateChannel;
  rollbackWindowDays: number;
  autoRollbackThreshold: number;
  checkIntervalHours: number;
  updateServerUrl: string;
  enableTelemetry: boolean;
  cacheRetentionDays: number;
}

const CONFIG_FILE = 'update-config.json';
const DEFAULT_CONFIG_URL = 'https://updates.sage.app';

export class ConfigManager {
  private configPath: string;
  private hmacSecret: string;

  constructor() {
    this.configPath = path.join(app.getPath('userData'), CONFIG_FILE);
    this.hmacSecret = getUpdateHmacSecret();
  }

  async getConfig(): Promise<UpdateConfig> {
    try {
      const data = await fs.readFile(this.configPath, 'utf-8');
      const parsed: unknown = JSON.parse(data);
      if (!this.isRecord(parsed)) {
        throw new Error('Invalid update config: expected an object');
      }
      if (typeof parsed.hmac !== 'string') {
        // Read legacy unsigned configs so existing installations can migrate on next write.
        return this.validateConfig(parsed);
      }
      const { hmac, ...config } = parsed;
      const expected = this.computeHmac(JSON.stringify(config));
      if (!this.safeEqual(hmac, expected)) {
        throw new Error('Invalid update config: integrity check failed');
      }
      return this.validateConfig(config);
    } catch (error) {
      if (error instanceof Error && error.message.startsWith('Invalid update config')) {
        console.warn(error.message);
      }
      return this.getDefaultConfig();
    }
  }

  async setConfig(config: UpdateConfig): Promise<void> {
    const validated = this.validateConfig(config);
    const configJson = JSON.stringify(validated);
    const data = JSON.stringify({ ...validated, hmac: this.computeHmac(configJson) }, null, 2);
    const temporaryPath = `${this.configPath}.${process.pid}.tmp`;
    await fs.writeFile(temporaryPath, data, {
      encoding: 'utf-8',
      mode: 0o600,
    });
    await fs.rename(temporaryPath, this.configPath);
  }

  private validateConfig(value: unknown): UpdateConfig {
    if (typeof value !== 'object' || value === null || Array.isArray(value)) {
      throw new Error('Invalid update config: expected an object');
    }
    const config = value as Record<string, unknown>;
    if (!['manual', 'auto-download', 'auto-install'].includes(String(config.updateStrategy))) {
      throw new Error('Invalid update config.updateStrategy');
    }
    if (!['stable', 'beta', 'alpha'].includes(String(config.channel))) {
      throw new Error('Invalid update config.channel');
    }
    for (const field of [
      'rollbackWindowDays',
      'autoRollbackThreshold',
      'checkIntervalHours',
      'cacheRetentionDays',
    ]) {
      if (
        typeof config[field] !== 'number' ||
        !Number.isSafeInteger(config[field]) ||
        config[field] < 0
      ) {
        throw new Error(`Invalid update config.${field}`);
      }
    }
    if (
      typeof config.updateServerUrl !== 'string' ||
      !this.isTrustedServerUrl(config.updateServerUrl)
    ) {
      throw new Error('Invalid update config.updateServerUrl');
    }
    if (typeof config.enableTelemetry !== 'boolean') {
      throw new Error('Invalid update config.enableTelemetry');
    }
    return {
      updateStrategy: config.updateStrategy as UpdateStrategy,
      channel: config.channel as UpdateChannel,
      rollbackWindowDays: config.rollbackWindowDays as number,
      autoRollbackThreshold: config.autoRollbackThreshold as number,
      checkIntervalHours: config.checkIntervalHours as number,
      updateServerUrl: config.updateServerUrl as string,
      enableTelemetry: config.enableTelemetry,
      cacheRetentionDays: config.cacheRetentionDays as number,
    };
  }

  private isTrustedServerUrl(value: string): boolean {
    try {
      const url = new URL(value);
      return (
        url.protocol === 'https:' &&
        url.hostname.length > 0 &&
        url.username === '' &&
        url.password === '' &&
        (url.pathname === '' || url.pathname === '/')
      );
    } catch {
      return false;
    }
  }

  private isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value);
  }

  private computeHmac(data: string): string {
    return crypto.createHmac('sha256', this.hmacSecret).update(data).digest('hex');
  }

  private safeEqual(actual: string, expected: string): boolean {
    const actualBuffer = Buffer.from(actual, 'utf8');
    const expectedBuffer = Buffer.from(expected, 'utf8');
    return (
      actualBuffer.length === expectedBuffer.length &&
      crypto.timingSafeEqual(actualBuffer, expectedBuffer)
    );
  }
  private getDefaultConfig(): UpdateConfig {
    return {
      updateStrategy: 'auto-download',
      channel: 'stable',
      rollbackWindowDays: 7,
      autoRollbackThreshold: 3,
      checkIntervalHours: 24,
      updateServerUrl: DEFAULT_CONFIG_URL,
      enableTelemetry: false,
      cacheRetentionDays: 30,
    };
  }
}
