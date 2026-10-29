// electron/feedback/feedbackConfig.ts
//
// 持久化用户反馈系统配置：管理员转发脚本 URL + 共享密钥 + 安装 UUID。
// 模式参照 electron/update/providerStore.ts：
//   - electron-store 存 JSON（明文 URL + base64 加密密钥 + UUID）
//   - Electron safeStorage 加密共享密钥（不可用时降级：chmod 0600 + warn 一次）
//
// 设计见 docs/plans/2026-10-29_direct-feedback-channel.md §1 / §4。

import Store from 'electron-store';
import { safeStorage } from 'electron';
import * as crypto from 'node:crypto';
import * as fs from 'node:fs';

import { logger } from '../logger';

interface FeedbackConfigSchema {
  'feedback.managerUrl': string;
  'feedback.sharedSecretEncrypted': string;
  'feedback.installationUuid': string;
}

const STORE_NAME = 'sage-feedback';
const KEY_URL = 'feedback.managerUrl';
const KEY_SECRET = 'feedback.sharedSecretEncrypted';
const KEY_UUID = 'feedback.installationUuid';

/** Spec §6 风险缓解：safeStorage 不可用时明文 + 0600 + 启动期 warn 一次。 */
let _degradationWarned = false;

export class FeedbackConfig {
  private readonly store: Store<FeedbackConfigSchema>;

  constructor() {
    this.store = new Store<FeedbackConfigSchema>({ name: STORE_NAME });
    this.ensureInstallationUuid();
  }

  /** 管理员转发脚本的 URL（如 "http://10.0.0.5:8900"）。未配置时返回空字符串。 */
  getManagerUrl(): string {
    return this.store.get(KEY_URL, '');
  }

  /** 设置管理员 URL（明文保存；允许空串表示清空）。 */
  setManagerUrl(url: string): void {
    this.store.set(KEY_URL, url.trim());
  }

  /** 读取共享密钥（运行时明文）。未配置时返回空字符串。 */
  getSharedSecret(): string {
    const raw = this.store.get(KEY_SECRET, '');
    if (!raw) return '';
    if (safeStorage.isEncryptionAvailable()) {
      try {
        return safeStorage.decryptString(Buffer.from(raw, 'base64'));
      } catch (err) {
        logger.warn('[feedback] failed to decrypt shared secret; treating as unset', {
          err: String(err),
        });
        return '';
      }
    }
    // Linux 降级路径：store 里存的就是明文
    return raw;
  }

  /** 设置共享密钥（safeStorage 可用时加密存储）。 */
  setSharedSecret(secret: string): void {
    if (!secret) {
      this.store.set(KEY_SECRET, '');
      return;
    }
    if (safeStorage.isEncryptionAvailable()) {
      const encrypted = safeStorage.encryptString(secret).toString('base64');
      this.store.set(KEY_SECRET, encrypted);
      return;
    }
    // 降级：明文 + 0600 + warn 一次
    this.store.set(KEY_SECRET, secret);
    this.applyDegradationHardening();
  }

  /** 是否已配置转发目标（URL 非空 + 密钥非空）。syncer 启动前据此决定是否跑。 */
  isConfigured(): boolean {
    return Boolean(this.getManagerUrl() && this.getSharedSecret());
  }

  /** 每个安装实例的稳定 UUID（首次调用时生成并固化，之后只读）。 */
  getInstallationUuid(): string {
    return this.ensureInstallationUuid();
  }

  /** 清空全部反馈配置（用户登出 / 重置设置时使用）。 */
  clear(): void {
    this.store.delete(KEY_URL);
    this.store.delete(KEY_SECRET);
    // 不删 installationUuid：换机/重装才变，普通重置保留便于追溯
  }

  // ==================== Internals ====================

  private ensureInstallationUuid(): string {
    const existing = this.store.get(KEY_UUID, '');
    if (existing) return existing;
    const uuid = crypto.randomUUID();
    this.store.set(KEY_UUID, uuid);
    return uuid;
  }

  private applyDegradationHardening(): void {
    try {
      const p = this.store.path;
      if (p && fs.existsSync(p)) fs.chmodSync(p, 0o600);
    } catch (err) {
      logger.warn('[feedback] failed to chmod 0600 on degraded store', { err: String(err) });
    }
    if (!_degradationWarned) {
      _degradationWarned = true;
      logger.warn(
        '[feedback] safeStorage unavailable; shared secret stored plaintext in ' +
          'electron-store JSON with 0600 file perms. Do not share this file.',
      );
    }
  }
}

/** 单例 —— 与 ProviderStore 同级别，整个 Electron main 进程共享一份。 */
let _instance: FeedbackConfig | null = null;

export function getFeedbackConfig(): FeedbackConfig {
  if (!_instance) _instance = new FeedbackConfig();
  return _instance;
}
