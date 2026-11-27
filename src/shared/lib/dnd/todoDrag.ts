/**
 * 待办拖拽排序 / 拖拽嵌套的纯函数模块（P1）。
 *
 * 职责:
 *   1. 落点判定（行内三分区：嵌套 / 前 / 后）
 *   2. 嵌套合法性（两层上限）
 *   3. 后端 move 请求的构造（三态 ``target_parent_id``）
 *   4. 乐观重排（本地数组按落点重排 + 同层 ``sort_order`` 重编号）
 *
 * 设计原则（与 ``siderOrder.ts`` 一致）:
 *   - 不依赖 React / DOM，可直接单测
 *   - 所有函数 immutable（返回新数组，不修改入参）
 *
 * 落点语义（与后端 ``backend/services/todo_order.py`` 对齐）:
 *   - ``before`` / ``after`` —— 相对参照待办落位，目标层**跟随参照待办所在层**
 *   - ``inside``          —— 成为参照待办的子任务（仅顶层行可作为落点）
 */
import type { TodoDropZone } from '../../api/types';

/** 落点区域：插到目标之前 / 插到目标之后 / 成为目标的子任务。 */
export type DropZone = TodoDropZone;

/**
 * 拖拽所需的最小待办形状。
 *
 * 只声明 ``id`` / ``parent_id`` / ``sort_order`` 三项 —— 它们是排序与层级判定
 * 唯一用到的字段。用结构类型而非直接依赖 ``Todo``，让本模块不牵扯 API 层。
 */
export interface TodoOrderEntry {
  id: number;
  parent_id?: number | null;
  sort_order?: number | null;
}

/** 同层相邻两项的默认步长 —— 与后端 ``todo_order.SORT_STEP`` 保持一致。 */
export const SORT_STEP = 1024;

/** 三分区横向占比：左 1/3 嵌套、中 1/3 前、右 1/3 后。 */
const NEST_ZONE_RATIO = 1 / 3;
const BEFORE_ZONE_RATIO = 2 / 3;

/** 目标行的外接矩形（只需 left / width）。 */
export interface DropRect {
  left: number;
  width: number;
}

/**
 * 落点判定。
 *
 * ``allowNest`` 为真时行内分三区（左 1/3 嵌套 / 中 1/3 前 / 右 1/3 后）；
 * 为假时只分两区（前半 = 前、后半 = 后）—— 树形视图不提供「变子任务」。
 */
export function computeDropZone(clientX: number, rect: DropRect, allowNest: boolean): DropZone {
  if (!(rect.width > 0)) return 'before';
  const ratio = (clientX - rect.left) / rect.width;
  if (!allowNest) {
    return ratio < 0.5 ? 'before' : 'after';
  }
  if (ratio < NEST_ZONE_RATIO) return 'inside';
  if (ratio < BEFORE_ZONE_RATIO) return 'before';
  return 'after';
}

/**
 * 能否把被拖行拖成目标的子任务。
 *
 * 层级上限两层（顶层 + 子任务），因此：
 *   - 目标本身是子任务 → 会变成第三层，不行；
 *   - 被拖行已经带子任务 → 它的子任务会变成第三层，不行；
 *   - 不能自己拖进自己。
 */
export function canNestInto(
  dragged: TodoOrderEntry,
  target: TodoOrderEntry,
  draggedHasChildren: boolean,
): boolean {
  if (dragged.id === target.id) return false;
  if (target.parent_id != null) return false;
  if (draggedHasChildren) return false;
  return true;
}

/** 所属层（顶层归一为 0，与后端 ``COALESCE(parent_id, 0)`` 同口径）。 */
export function layerOf(entry: TodoOrderEntry): number {
  return entry.parent_id ?? 0;
}

export interface DropTargetOptions {
  /** 是否允许「变成子任务」的落区。 */
  allowNest: boolean;
  /** 是否只允许同层重排（树形视图用）。 */
  sameLayerOnly: boolean;
}

/** 目标行是否是合法落点。 */
export function isValidDropTarget(
  dragged: TodoOrderEntry,
  target: TodoOrderEntry,
  options: DropTargetOptions,
): boolean {
  if (dragged.id === target.id) return false;
  if (options.sameLayerOnly) {
    return layerOf(dragged) === layerOf(target);
  }
  return true;
}

/**
 * 后端 move 请求体。
 *
 * ``target_parent_id`` 是三态：
 *   - 省略 → 目标层跟随参照待办所在层（后端 ``todo_order.INHERIT``）；
 *   - 显式 ``null`` → 强制回顶层；
 *   - 给 id → 成为该待办的子任务。
 */
export interface TodoMoveRequest {
  position: 'before' | 'after';
  reference_id?: number;
  target_parent_id?: number | null;
}

/**
 * 构造后端 move 请求。
 *
 * ``before`` / ``after`` **必须省略** ``target_parent_id`` —— 显式 ``null``
 * 的语义是「强制回顶层」，不是「跟随参照物所在层」。IPC 的 JSON 序列化会
 * 丢掉 ``undefined``，所以「省略」只能靠根本不写这个 key 来表达。
 */
export function buildMoveRequest(targetId: number, zone: DropZone): TodoMoveRequest {
  if (zone === 'inside') {
    // 成为子任务：追加到目标子层末尾（不给 reference_id，后端按层末尾落位）。
    return { position: 'after', target_parent_id: targetId };
  }
  return { position: zone, reference_id: targetId };
}

/**
 * 手工次序排序：层 → ``sort_order`` → ``id``。
 *
 * 与后端 ``todo_filters.sort_expression('manual')`` 同口径，保证本地乐观
 * 数组与服务端返回的数组顺序一致。
 */
export function sortByManualOrder<T extends TodoOrderEntry>(todos: T[]): T[] {
  return [...todos].sort((a, b) => {
    const layerDiff = layerOf(a) - layerOf(b);
    if (layerDiff !== 0) return layerDiff;
    const orderDiff = (a.sort_order ?? 0) - (b.sort_order ?? 0);
    if (orderDiff !== 0) return orderDiff;
    return a.id - b.id;
  });
}

/**
 * 乐观重排：把被拖行按落点移到目标位置，并重编目标层的 ``sort_order``。
 *
 * 落点非法（找不到行 / 拖到自己）时**原样返回入参**（同一引用），
 * 调用方据此判断「这次移动无需发请求」。
 */
export function applyOptimisticMove<T extends TodoOrderEntry>(
  todos: T[],
  draggedId: number,
  targetId: number,
  zone: DropZone,
): T[] {
  const dragged = todos.find((t) => t.id === draggedId);
  const target = todos.find((t) => t.id === targetId);
  if (!dragged || !target || draggedId === targetId) return todos;

  const nextParentId = zone === 'inside' ? target.id : (target.parent_id ?? null);
  const layer = todos.filter((t) => (t.parent_id ?? null) === nextParentId && t.id !== draggedId);
  const targetIndex = layer.findIndex((t) => t.id === targetId);
  const insertAt =
    zone === 'inside'
      ? layer.length
      : targetIndex < 0
        ? layer.length
        : targetIndex + (zone === 'after' ? 1 : 0);

  const ordered = [...layer];
  ordered.splice(insertAt, 0, dragged);

  const orderById = new Map<number, number>();
  ordered.forEach((item, index) => {
    orderById.set(item.id, (index + 1) * SORT_STEP);
  });

  const next = todos.map((t) => {
    if (t.id === draggedId) {
      return { ...t, parent_id: nextParentId, sort_order: orderById.get(draggedId) ?? 0 };
    }
    const order = orderById.get(t.id);
    return order === undefined ? t : { ...t, sort_order: order };
  });

  return sortByManualOrder(next);
}
