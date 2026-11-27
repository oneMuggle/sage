import { describe, expect, it } from 'vitest';

import {
  SORT_STEP,
  applyOptimisticMove,
  buildMoveRequest,
  canNestInto,
  computeDropZone,
  isValidDropTarget,
  layerOf,
  sortByManualOrder,
  type TodoOrderEntry,
} from '../todoDrag';

/** 顶层待办（parent_id 为 null）。 */
function top(id: number, sortOrder?: number): TodoOrderEntry {
  return { id, parent_id: null, sort_order: sortOrder ?? 0 };
}

/** 子任务（parent_id 非 null）。 */
function child(id: number, parentId: number, sortOrder?: number): TodoOrderEntry {
  return { id, parent_id: parentId, sort_order: sortOrder ?? 0 };
}

describe('computeDropZone', () => {
  const rect = { left: 0, width: 300 };

  it('splits the row into three zones when nesting is allowed', () => {
    // 左 1/3 → 嵌套
    expect(computeDropZone(10, rect, true)).toBe('inside');
    expect(computeDropZone(99, rect, true)).toBe('inside');
    // 中 1/3 → 前
    expect(computeDropZone(150, rect, true)).toBe('before');
    // 右 1/3 → 后
    expect(computeDropZone(250, rect, true)).toBe('after');
    expect(computeDropZone(299, rect, true)).toBe('after');
  });

  it('splits the row into two zones when nesting is not allowed', () => {
    expect(computeDropZone(10, rect, false)).toBe('before');
    expect(computeDropZone(149, rect, false)).toBe('before');
    expect(computeDropZone(150, rect, false)).toBe('after');
    expect(computeDropZone(299, rect, false)).toBe('after');
  });

  it('offsets by the row left edge', () => {
    const offsetRect = { left: 100, width: 300 };
    expect(computeDropZone(110, offsetRect, true)).toBe('inside');
    expect(computeDropZone(200, offsetRect, true)).toBe('before');
    expect(computeDropZone(390, offsetRect, true)).toBe('after');
  });

  it('falls back to before for a zero-width row', () => {
    expect(computeDropZone(10, { left: 0, width: 0 }, true)).toBe('before');
    expect(computeDropZone(10, { left: 0, width: 0 }, false)).toBe('before');
  });
});

describe('canNestInto', () => {
  it('allows a top-level row without children to become a subtask', () => {
    expect(canNestInto(top(1), top(2), false)).toBe(true);
  });

  it('rejects nesting into a subtask (would exceed two levels)', () => {
    expect(canNestInto(top(1), child(2, 9), false)).toBe(false);
  });

  it('rejects nesting a row that already has children', () => {
    expect(canNestInto(top(1), top(2), true)).toBe(false);
  });

  it('rejects dropping a row into itself', () => {
    expect(canNestInto(top(1), top(1), false)).toBe(false);
  });
});

describe('layerOf', () => {
  it('normalises top-level rows to 0', () => {
    expect(layerOf(top(1))).toBe(0);
    expect(layerOf({ id: 2, parent_id: undefined })).toBe(0);
  });

  it('uses the parent id for subtasks', () => {
    expect(layerOf(child(3, 7))).toBe(7);
  });
});

describe('isValidDropTarget', () => {
  it('rejects dropping a row onto itself', () => {
    expect(isValidDropTarget(top(1), top(1), { allowNest: true, sameLayerOnly: false })).toBe(
      false,
    );
  });

  it('allows cross-layer moves when same-layer is not enforced', () => {
    expect(isValidDropTarget(top(1), child(2, 9), { allowNest: true, sameLayerOnly: false })).toBe(
      true,
    );
  });

  it('enforces same-layer reordering in tree view', () => {
    expect(isValidDropTarget(top(1), top(2), { allowNest: true, sameLayerOnly: true })).toBe(true);
    expect(isValidDropTarget(top(1), child(2, 9), { allowNest: true, sameLayerOnly: true })).toBe(
      false,
    );
  });

  it('allows reordering siblings within the same parent', () => {
    expect(
      isValidDropTarget(child(1, 5), child(2, 5), { allowNest: true, sameLayerOnly: true }),
    ).toBe(true);
  });
});

describe('buildMoveRequest', () => {
  it('omits target_parent_id for before/after so the layer follows the reference', () => {
    const before = buildMoveRequest(7, 'before');
    expect(before).toEqual({ position: 'before', reference_id: 7 });
    expect('target_parent_id' in before).toBe(false);

    const after = buildMoveRequest(7, 'after');
    expect(after).toEqual({ position: 'after', reference_id: 7 });
    expect('target_parent_id' in after).toBe(false);
  });

  it('targets the parent id for the inside zone', () => {
    const inside = buildMoveRequest(7, 'inside');
    expect(inside).toEqual({ position: 'after', target_parent_id: 7 });
    expect('reference_id' in inside).toBe(false);
  });
});

describe('sortByManualOrder', () => {
  it('orders by layer, then sort_order, then id', () => {
    const sorted = sortByManualOrder([child(30, 5, 20), top(1, 30), top(2, 10), child(20, 5, 10)]);
    expect(sorted.map((t) => t.id)).toEqual([2, 1, 20, 30]);
  });

  it('does not mutate the input array', () => {
    const input = [top(2, 10), top(1, 30)];
    const copy = [...input];
    sortByManualOrder(input);
    expect(input).toEqual(copy);
  });
});

describe('applyOptimisticMove', () => {
  it('returns the same array reference for an illegal move', () => {
    const todos = [top(1, 1024), top(2, 2048)];
    expect(applyOptimisticMove(todos, 1, 1, 'before')).toBe(todos);
    expect(applyOptimisticMove(todos, 99, 1, 'before')).toBe(todos);
    expect(applyOptimisticMove(todos, 1, 99, 'before')).toBe(todos);
  });

  it('moves a row after its target and renumbers the layer', () => {
    const todos = [top(1, 1024), top(2, 2048), top(3, 3072)];
    const next = applyOptimisticMove(todos, 1, 3, 'after');
    expect(next.map((t) => t.id)).toEqual([2, 3, 1]);
    expect(next.map((t) => t.sort_order)).toEqual([1024, 2048, 3072]);
  });

  it('moves a row before its target', () => {
    const todos = [top(1, 1024), top(2, 2048), top(3, 3072)];
    const next = applyOptimisticMove(todos, 3, 1, 'before');
    expect(next.map((t) => t.id)).toEqual([3, 1, 2]);
  });

  it('reattaches a row as a subtask of the target', () => {
    const todos = [top(1, 1024), top(2, 2048)];
    const next = applyOptimisticMove(todos, 2, 1, 'inside');
    const moved = next.find((t) => t.id === 2);
    expect(moved?.parent_id).toBe(1);
    // 子任务排到父任务之后
    expect(next.map((t) => t.id)).toEqual([1, 2]);
  });

  it('keeps sibling ordering intact when reordering inside a parent layer', () => {
    const todos = [top(1, 1024), child(2, 1, 1024), child(3, 1, 2048)];
    const next = applyOptimisticMove(todos, 3, 2, 'before');
    expect(next.map((t) => t.id)).toEqual([1, 3, 2]);
    expect(next.find((t) => t.id === 3)?.parent_id).toBe(1);
    expect(next.find((t) => t.id === 2)?.parent_id).toBe(1);
  });

  it('does not mutate the input array or its entries', () => {
    const todos = [top(1, 1024), top(2, 2048)];
    const snapshot = JSON.stringify(todos);
    applyOptimisticMove(todos, 1, 2, 'after');
    expect(JSON.stringify(todos)).toBe(snapshot);
  });

  it('uses the same step size as the backend', () => {
    const todos = [top(1, 1024), top(2, 2048)];
    const next = applyOptimisticMove(todos, 1, 2, 'after');
    expect(next[0].sort_order).toBe(SORT_STEP);
    expect(next[1].sort_order).toBe(SORT_STEP * 2);
  });
});
