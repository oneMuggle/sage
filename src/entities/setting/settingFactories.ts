/**
 * 设置元数据工厂函数。
 *
 * 从 `settingsRegistry.ts` 拆出，避免注册表越过架构行数棘轮；
 * 由 `settingsRegistry.ts` 重新导出，对外 API 不变。
 */

import type { SettingMetadata } from './metadata';

export const booleanSetting = (
  key: string,
  label: string,
  description: string,
  storage: SettingMetadata['storage'],
  defaultValue: boolean,
  applyMode: SettingMetadata['applyMode'] = 'immediate',
  visibility: SettingMetadata['visibility'] = 'basic',
): SettingMetadata => ({
  key,
  label,
  description,
  scope: 'global',
  storage,
  defaultValue,
  applyMode,
  visibility,
  riskLevel: 'low',
  constraints: { type: 'boolean' },
});

export const numberSetting = (
  key: string,
  label: string,
  description: string,
  storage: SettingMetadata['storage'],
  defaultValue: number,
  min: number,
  max?: number,
  applyMode: SettingMetadata['applyMode'] = 'next-request',
  visibility: SettingMetadata['visibility'] = 'advanced',
): SettingMetadata => ({
  key,
  label,
  description,
  scope: 'global',
  storage,
  defaultValue,
  applyMode,
  visibility,
  riskLevel: 'medium',
  constraints: { type: 'number', min, ...(max === undefined ? {} : { max }) },
});

export const enumSetting = (
  key: string,
  label: string,
  description: string,
  storage: SettingMetadata['storage'],
  defaultValue: string,
  options: Array<{ value: string; label: string }>,
  applyMode: SettingMetadata['applyMode'] = 'immediate',
  visibility: SettingMetadata['visibility'] = 'basic',
): SettingMetadata => ({
  key,
  label,
  description,
  scope: 'global',
  storage,
  defaultValue,
  applyMode,
  visibility,
  riskLevel: 'low',
  constraints: { type: 'enum', options },
});

export const orchNumber = (
  key: string,
  label: string,
  description: string,
  defaultValue: number,
  min: number,
  max?: number,
): SettingMetadata => ({
  ...numberSetting(key, label, description, 'app_settings', defaultValue, min, max, 'next-run'),
  storageKey: key,
});
