/**
 * 侧边栏拖拽排序的纯函数模块。
 *
 * 职责:
 *   1. 序列化/反序列化 stored order(纯字符串 ↔ 字符串数组)
 *   2. reconcile stored order 与 current items,产出统一顺序
 *   3. 提供"在两个位置之间移动 id"的不可变工具
 *
 * 设计原则:
 *   - 不依赖 React / DOM / localStorage
 *   - 所有函数 immutable(返回新数组,不修改入参)
 *   - 防御性:任何 null/undefined/JSON 错误都返回 [] 或保底行为
 */

export type SiderOrder = string[];

export const EMPTY_ORDER: readonly string[] = Object.freeze([]);

/**
 * Parse a raw localStorage value into a SiderOrder.
 * Accepts: JSON-stringified string[], or null/undefined/"".
 * Rejects: anything else (returns []).
 */
export function readStoredSiderOrder(raw: string | null | undefined): SiderOrder {
  if (raw == null || raw === '') return [];
  try {
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((x): x is string => typeof x === 'string');
  } catch {
    return [];
  }
}

/**
 * Serialize a SiderOrder to a JSON string suitable for localStorage.
 * Pure: does not touch localStorage.
 */
export function writeStoredSiderOrder(order: SiderOrder): string {
  return JSON.stringify(order);
}

/**
 * Reconcile a previously-stored order against the current item ids.
 *
 * 规则:
 *   - prev 中仍存在于 current 的 id,保持其相对顺序
 *   - current 中新出现的 id,追加到末尾(保持 current 中的相对顺序)
 *   - prev 中已不存在的 id,丢弃
 *
 * 不修改任何入参,返回新数组。
 */
export function reconcileStoredSiderOrder(
  prev: SiderOrder,
  current: SiderOrder,
): SiderOrder {
  const currentSet = new Set(current);
  const kept: string[] = [];
  for (const id of prev) {
    if (currentSet.has(id)) kept.push(id);
  }
  const keptSet = new Set(kept);
  const added: string[] = [];
  for (const id of current) {
    if (!keptSet.has(id)) added.push(id);
  }
  // added 已经按 current 顺序遍历,自然有序
  return [...kept, ...added];
}

/**
 * Sort an array of items by a stored order.
 * Items whose id is not in `order` are appended at the end, preserving their input order.
 */
export function sortSiderItemsByStoredOrder<T extends { id: string }>(
  items: readonly T[],
  order: SiderOrder,
): T[] {
  if (order.length === 0) return [...items];
  const orderIndex = new Map<string, number>();
  order.forEach((id, idx) => orderIndex.set(id, idx));
  const sorted = [...items].sort((a, b) => {
    const ai = orderIndex.has(a.id) ? (orderIndex.get(a.id) as number) : Number.POSITIVE_INFINITY;
    const bi = orderIndex.has(b.id) ? (orderIndex.get(b.id) as number) : Number.POSITIVE_INFINITY;
    return ai - bi;
  });
  return sorted;
}

/**
 * 两个顺序是否完全一致(逐位相等,长度也相等)。
 * 用 === 而非 deep-equal:顺序数组里只有 string,引用等价即可。
 */
export function areSiderOrdersEqual(a: SiderOrder, b: SiderOrder): boolean {
  if (a === b) return true;
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) {
    if (a[i] !== b[i]) return false;
  }
  return true;
}

/**
 * 在 immutable 风格下,把 `from` 位置上的 id 移动到 `to` 位置(类似 dnd-kit 的 arrayMove)。
 * - from === to 时返回入参的浅拷贝(避免无意义变更)。
 * - 越界索引会抛 Error(由调用方保证)。
 */
export function reorderSiderIds(
  order: SiderOrder,
  from: number,
  to: number,
): SiderOrder {
  if (from < 0 || from >= order.length) {
    throw new Error(`reorderSiderIds: from out of range (${from} / ${order.length})`);
  }
  if (to < 0 || to >= order.length) {
    throw new Error(`reorderSiderIds: to out of range (${to} / ${order.length})`);
  }
  if (from === to) return [...order];
  const next = [...order];
  const [moved] = next.splice(from, 1);
  next.splice(to, 0, moved);
  return next;
}
