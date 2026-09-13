// src/features/chat/entityRefs.ts
//
// 对标 S3 (2026-09-13, 竞品对标 §2.2): 聊天输入 `@memory:` / `@wiki:` /
// `@skill:` / `@agent:` 实体引用。前端只负责补全与插入 token；解析与
// 注入由后端 backend/chat/entity_refs.py 在发送时完成。

export type EntityRefKind = 'memory' | 'wiki' | 'skill' | 'agent';

export interface EntityKindSuggestion {
  kind: EntityRefKind;
  /** 插入到输入框的 token（含 @ 与冒号，不含查询） */
  token: string;
}

export const ENTITY_REF_KINDS: readonly EntityRefKind[] = ['memory', 'wiki', 'skill', 'agent'];

const KIND_RE = /^(memory|wiki|skill|agent):(.*)$/;

/**
 * 判断当前 @ 查询是否已经进入实体引用模式（`memory:xxx`）。
 * 返回 kind 与已输入的查询；否则 null。
 */
export function parseEntityRefQuery(
  query: string | null,
): { kind: EntityRefKind; query: string } | null {
  if (query == null) return null;
  const m = KIND_RE.exec(query);
  if (!m) return null;
  return { kind: m[1] as EntityRefKind, query: m[2] };
}

/**
 * 根据 @ 后已输入的前缀给出实体类型候选。
 * - 空前缀 → 全部四类；
 * - 前缀为某类的开头（不区分大小写）→ 匹配的类；
 * - 已含冒号或不匹配任何类 → []（此时只显示文件补全）。
 */
export function getEntityKindSuggestions(query: string | null): EntityKindSuggestion[] {
  if (query == null || query.includes(':') || query.includes('/')) return [];
  const lower = query.toLowerCase();
  return ENTITY_REF_KINDS.filter((k) => k.startsWith(lower)).map((kind) => ({
    kind,
    token: `@${kind}:`,
  }));
}
