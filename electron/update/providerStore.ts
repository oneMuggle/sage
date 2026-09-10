// electron/update/providerStore.ts
import Store from 'electron-store';
import { safeStorage } from 'electron';
import * as crypto from 'node:crypto';
import * as fs from 'node:fs';
import { logger } from '../logger';
import type { ProviderInstanceConfig, ProviderType } from './providerConfig';

interface StoreSchema { 'update.providers': ProviderInstanceConfig[]; }

const STORE_KEY = 'update.providers';
const SENSITIVE_TYPES: ProviderType[] = ['github', 'gitee', 'gitlab'];

/** Spec §4.5: warn once per process when safeStorage degrades to plaintext. */
let _degradationWarned = false;

export class ProviderStore {
  private store: Store<StoreSchema>;

  constructor() {
    this.store = new Store<StoreSchema>({ name: 'sage-update' });
  }

  async list(): Promise<ProviderInstanceConfig[]> {
    const raw = this.store.get(STORE_KEY) ?? [];
    return raw.map((c) => this.decryptSensitive(c));
  }

  async get(id: string): Promise<ProviderInstanceConfig | null> {
    const list = await this.list();
    return list.find((c) => c.id === id) ?? null;
  }

  async add(cfg: Omit<ProviderInstanceConfig, 'id' | 'createdAt' | 'updatedAt'>): Promise<string> {
    const id = crypto.randomUUID();
    const now = new Date().toISOString();
    const full: ProviderInstanceConfig = { ...cfg, id, createdAt: now, updatedAt: now };
    const list = this.store.get(STORE_KEY) ?? [];
    if (full.isDefault) list.forEach((c) => (c.isDefault = false));
    list.push(this.encryptSensitive(full));
    this.store.set(STORE_KEY, list);
    return id;
  }

  async update(id: string, patch: Partial<ProviderInstanceConfig>): Promise<void> {
    const list = this.store.get(STORE_KEY) ?? [];
    const idx = list.findIndex((c) => c.id === id);
    if (idx === -1) throw new Error(`Provider not found: ${id}`);
    const merged = { ...list[idx], ...patch, id, updatedAt: new Date().toISOString() };
    list[idx] = this.encryptSensitive(merged);
    if (patch.isDefault) {
      list.forEach((c, i) => { if (i !== idx) c.isDefault = false; });
    }
    this.store.set(STORE_KEY, list);
  }

  async remove(id: string): Promise<void> {
    const list = this.store.get(STORE_KEY) ?? [];
    const target = list.find((c) => c.id === id);
    if (!target) return;
    if (target.isDefault) throw new Error('Cannot remove default provider; set another provider as default first.');
    this.store.set(STORE_KEY, list.filter((c) => c.id !== id));
  }

  async setDefault(id: string): Promise<void> {
    const list = this.store.get(STORE_KEY) ?? [];
    list.forEach((c) => (c.isDefault = c.id === id));
    this.store.set(STORE_KEY, list);
  }

  private encryptSensitive(cfg: ProviderInstanceConfig): ProviderInstanceConfig {
    if (safeStorage.isEncryptionAvailable()) {
      const c: ProviderInstanceConfig = { ...cfg };
      if (SENSITIVE_TYPES.includes(cfg.type)) {
        // Sensitive provider configs carry `token` at runtime; narrow the union
        // structurally so we can read/overwrite it without `as any`.
        const tokenCfg = c.config as { token?: string };
        if (tokenCfg.token) {
          c.config = {
            ...c.config,
            token: safeStorage.encryptString(tokenCfg.token).toString('base64'),
          } as ProviderInstanceConfig['config'];
          c._tokenEncrypted = true;
        }
      }
      return c;
    }
    // Linux 降级：明文 + chmod 0600 + 启动 warn 一次（spec §4.5）
    try {
      const p = this.store.path;
      if (p && fs.existsSync(p)) fs.chmodSync(p, 0o600);
    } catch (e) {
      logger.warn('[providers] failed to chmod 0600 on degradation store', { err: String(e) });
    }
    if (!_degradationWarned) {
      _degradationWarned = true;
      logger.warn(
        '[providers] safeStorage unavailable; provider tokens stored plaintext in ' +
          'electron-store JSON with 0600 file perms. Do not share this file.',
      );
    }
    const plain: ProviderInstanceConfig = { ...cfg, _tokenEncrypted: false };
    return plain;
  }

  private decryptSensitive(cfg: ProviderInstanceConfig): ProviderInstanceConfig {
    if (cfg._tokenEncrypted && safeStorage.isEncryptionAvailable()) {
      const c: ProviderInstanceConfig = { ...cfg };
      const tokenCfg = c.config as { token?: string };
      if (tokenCfg.token) {
        c.config = {
          ...c.config,
          token: safeStorage.decryptString(Buffer.from(tokenCfg.token, 'base64')),
        } as ProviderInstanceConfig['config'];
      }
      return c;
    }
    return cfg;
  }
}