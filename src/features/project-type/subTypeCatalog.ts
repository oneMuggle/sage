/**
 * L2 子类型目录解析工具 (2026-10-27)
 *
 * 项目类型分类系统 - Phase 10.3
 * 把后端返回的 L2 子类型 key 解析为可读标签；目录缺失时回退为 key 本身。
 */

import type { SubTypeDefinition, SubTypesCatalog } from '../../shared/api';

/**
 * 在两级类型目录中查找子类型定义（跨所有 L1 分组）。
 * 目录未加载（null/undefined）或 key 不存在时返回 null。
 */
export function findSubTypeDefinition(
  key: string,
  catalog: SubTypesCatalog | null | undefined,
): SubTypeDefinition | null {
  if (!catalog) return null;
  for (const definitions of Object.values(catalog.subTypes)) {
    const hit = definitions.find((d) => d.key === key);
    if (hit) return hit;
  }
  return null;
}

/** 解析子类型可读标签；未命中时回退为 key。 */
export function resolveSubTypeLabel(
  key: string,
  catalog: SubTypesCatalog | null | undefined,
): string {
  return findSubTypeDefinition(key, catalog)?.label ?? key;
}
