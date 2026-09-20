import type { UpdateConfig } from '../../../electron/updateConfig';
import { settingsClient, type PreferenceKey } from '../../shared/api/settingsClient';

import type { StorageBackend } from './metadata';
import { getSettingMetadata } from './settingsRegistry';
import { validateSettingValue } from './settingsValidation';
import type { AppSettings } from './types';

function preferenceKey(key: string): PreferenceKey {
  const metadata = getSettingMetadata(key);
  if (!metadata || metadata.storage !== 'preference') {
    throw new Error(`设置项不是 preference: ${key}`);
  }
  return (metadata.storageKey ?? key) as PreferenceKey;
}

function getStorage(key: string): StorageBackend {
  const metadata = getSettingMetadata(key);
  if (!metadata || metadata.visibility === 'internal') throw new Error(`未知或内部设置项: ${key}`);
  return metadata.storage;
}

function serializePreference(key: string, value: unknown): string {
  const metadata = getSettingMetadata(key);
  if (metadata?.constraints?.type === 'json') return JSON.stringify(value);
  return String(value);
}

function parsePreference<T>(key: string, value: string | null): T | null {
  if (value === null) return null;
  const metadata = getSettingMetadata(key);
  if (metadata?.constraints?.type !== 'json') return value as T;
  try {
    return JSON.parse(value) as T;
  } catch {
    return null;
  }
}

export async function readSetting<T>(key: string): Promise<T | null> {
  const storage = getStorage(key);
  if (storage === 'preference') {
    const raw = await settingsClient.getPreference<string>(preferenceKey(key));
    return parsePreference<T>(key, raw);
  }
  if (storage === 'app_settings') {
    const settings = await settingsClient.getSettings();
    if (!settings) return null;
    const path = key.split('.');
    let value: unknown = settings;
    for (const segment of path) value = (value as Record<string, unknown> | undefined)?.[segment];
    return (value as T | undefined) ?? null;
  }
  if (storage === 'electron') {
    if (key.startsWith('updates.')) {
      const config = await window.electronAPI?.updates.getConfig();
      if (!config) return null;
      return config[key.slice('updates.'.length) as keyof typeof config] as T;
    }
    if (key === 'closeToTray') {
      const result = await window.electronAPI?.getCloseToTray?.();
      return (result?.enabled ?? false) as T;
    }
  }
  if (storage === 'local') {
    return (window.localStorage.getItem(key) as T | null) ?? null;
  }
  throw new Error(`暂不支持通过通用适配器读取 ${storage} 设置: ${key}`);
}

export async function writeSetting<T>(key: string, value: T, category = 'general'): Promise<void> {
  const storage = getStorage(key);
  const error = validateSettingValue(key, value);
  if (error) throw new Error(error);

  if (storage === 'preference') {
    await settingsClient.setPreferenceStrict(
      preferenceKey(key),
      serializePreference(key, value),
      category,
    );
    return;
  }
  if (storage === 'app_settings') {
    const path = key.split('.');
    if (path.length === 1) {
      await settingsClient.setSettings({ [key]: value } as Partial<AppSettings>);
      return;
    }
    const current = await settingsClient.getSettings();
    if (!current) throw new Error(`无法读取设置后再写入: ${key}`);
    const root = path[0] as keyof AppSettings;
    const nested = {
      ...(current[root] as unknown as Record<string, unknown>),
      [path[1]]: value,
    };
    await settingsClient.setSettings({ [root]: nested } as Partial<AppSettings>);
    return;
  }
  if (storage === 'electron') {
    if (key.startsWith('updates.')) {
      const field = key.slice('updates.'.length) as keyof UpdateConfig;
      await window.electronAPI?.updates.setConfigPatch({ [field]: value });
      return;
    }
    if (key === 'closeToTray') {
      await window.electronAPI?.setCloseToTray?.(value as boolean);
      return;
    }
  }
  if (storage === 'local') {
    window.localStorage.setItem(key, typeof value === 'string' ? value : JSON.stringify(value));
    return;
  }
  throw new Error(`暂不支持通过通用适配器写入 ${storage} 设置: ${key}`);
}

export async function resetSetting(key: string): Promise<void> {
  const metadata = getSettingMetadata(key);
  await writeSetting(key, metadata?.defaultValue, 'settings-reset');
}
