import { getSettingMetadata } from './settingsRegistry';
import type { SettingMetadata } from './metadata';

function validateConstraint(metadata: SettingMetadata, value: unknown): string | null {
  const constraint = metadata.constraints;
  if (!constraint) return null;

  if (constraint.type === 'number') {
    if (typeof value !== 'number' || !Number.isFinite(value)) {
      return `${metadata.label}必须是有效数字`;
    }
    if (constraint.min !== undefined && value < constraint.min) {
      return `${metadata.label}不能小于 ${constraint.min}`;
    }
    if (constraint.max !== undefined && value > constraint.max) {
      return `${metadata.label}不能大于 ${constraint.max}`;
    }
  } else if (constraint.type === 'boolean' && typeof value !== 'boolean') {
    return `${metadata.label}必须是布尔值`;
  } else if (constraint.type === 'string' && typeof value !== 'string') {
    return `${metadata.label}必须是字符串`;
  } else if (constraint.type === 'enum') {
    const values = constraint.options?.map((option) => option.value) ?? [];
    if (typeof value !== 'string' || !values.includes(value)) {
      return `${metadata.label}的值无效`;
    }
  } else if (constraint.type === 'json' && (typeof value !== 'object' || value === null)) {
    return `${metadata.label}必须是对象或数组`;
  }

  if (
    constraint.pattern &&
    typeof value === 'string' &&
    !new RegExp(constraint.pattern).test(value)
  ) {
    return `${metadata.label}格式无效`;
  }
  return metadata.validate?.(value) ?? null;
}

export function validateSettingValue(key: string, value: unknown): string | null {
  const metadata = getSettingMetadata(key);
  if (!metadata) return `未知设置项: ${key}`;
  return validateConstraint(metadata, value);
}
