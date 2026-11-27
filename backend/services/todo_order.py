"""待办手工排序 —— 同层次序的分配与重排（P1 拖拽排序 / 拖拽嵌套）。

排序语义
--------
``todos.sort_order`` 是同层（同一 ``parent_id``）内的相对次序，REAL 步进值：

- 新建待办追加到所在层末尾 → ``max(sort_order) + SORT_STEP``；
- 拖到首位 → ``min(sort_order) - SORT_STEP``；
- 拖到两项之间 → 取两者中点 ``(prev + next) / 2``；
- 中点与两端的间距小于 ``MIN_GAP``（浮点精度耗尽）→ 整层按当前次序重排，
  重新以 ``SORT_STEP`` 为步长铺开，再写入目标位。

一次拖拽通常只改一行；只有间距耗尽时才会整层重写（``affected`` 相应变大）。

层级约束
--------
待办层级上限两层（顶层 + 子任务）：

- 目标父级必须是顶层行（``parent_id IS NULL``）；
- 被移动的行若已有子任务，不能塞进别人下面（否则成第三层）；
- 参照待办必须与目标层同层 —— 跨层「相对落位」没有意义。

``target_parent_id`` 省略时（``todo_order.INHERIT``）目标层跟随参照待办所在层；
参照待办也没给时落到顶层末尾。
"""
from __future__ import annotations

import sqlite3
from typing import Any, List, Optional, Tuple

# 同层相邻两项的默认步长；中点插入后两侧各留一半。
SORT_STEP = 1024.0
# 浮点间距下限：小于它就认为「中点这条路走到底了」，改走整层重排。
MIN_GAP = 1e-9


class _Inherit:
    """未显式指定目标父级 —— 目标层跟随参照待办所在层。"""

    __slots__ = ()

    def __repr__(self) -> str:  # pragma: no cover - 仅调试用
        return "INHERIT"


INHERIT = _Inherit()


class TodoOrderError(ValueError):
    """移动请求不合法（层级超限 / 自我嵌套 / 参照物不同层等）。"""


def _layer_rows(
    conn: sqlite3.Connection,
    parent_id: Optional[int],
    exclude_id: Optional[int] = None,
) -> List[sqlite3.Row]:
    """同层待办，按 ``(sort_order, id)`` 升序。

    ``parent_id is None`` 表示顶层 —— 必须用 ``IS NULL`` 判断，``= NULL``
    永远不匹配。
    """
    if parent_id is None:
        sql = "SELECT id, sort_order FROM todos WHERE parent_id IS NULL"
        params: Tuple[Any, ...] = ()
    else:
        sql = "SELECT id, sort_order FROM todos WHERE parent_id = ?"
        params = (parent_id,)
    if exclude_id is not None:
        sql += " AND id != ?"
        params = params + (exclude_id,)
    sql += " ORDER BY sort_order ASC, id ASC"
    return list(conn.execute(sql, params).fetchall())


def next_sort_order(
    conn: sqlite3.Connection,
    parent_id: Optional[int],
    exclude_id: Optional[int] = None,
) -> float:
    """新待办（或刚换父级的待办）应取的位置值：所在层的末尾。"""
    rows = _layer_rows(conn, parent_id, exclude_id=exclude_id)
    if not rows:
        return float(SORT_STEP)
    return float(rows[-1]["sort_order"] or 0) + SORT_STEP


def _insert_index(
    layer: List[sqlite3.Row], reference_id: Optional[int], position: str
) -> int:
    """参照待办在层内的落位下标；没有参照物时追加到末尾。"""
    if reference_id is None:
        return len(layer)
    for index, item in enumerate(layer):
        if item["id"] == reference_id:
            return index if position == "before" else index + 1
    # 参照待办不在本层（正常路径已在前面校验过）—— 兜底追加到末尾。
    return len(layer)


def _midpoint(
    prev_row: Optional[sqlite3.Row], next_row: Optional[sqlite3.Row]
) -> Tuple[float, bool]:
    """落位值，以及是否需要整层重排。"""
    if prev_row is None and next_row is None:
        return float(SORT_STEP), False
    if prev_row is None:
        high = float(next_row["sort_order"] or 0)
        value = high - SORT_STEP
        return value, (high - value) <= MIN_GAP
    if next_row is None:
        low = float(prev_row["sort_order"] or 0)
        value = low + SORT_STEP
        return value, (value - low) <= MIN_GAP
    low = float(prev_row["sort_order"] or 0)
    high = float(next_row["sort_order"] or 0)
    value = (low + high) / 2.0
    exhausted = (value - low) <= MIN_GAP or (high - value) <= MIN_GAP
    return value, exhausted


def _validate_dest_parent(
    conn: sqlite3.Connection,
    todo_id: int,
    current_parent: Optional[int],
    dest_parent: Optional[int],
) -> None:
    """目标层合法性：两层上限 + 不能自我嵌套 + 带子任务的行不能下沉。"""
    if dest_parent is None:
        return
    if dest_parent == todo_id:
        raise TodoOrderError("a todo cannot be its own parent")
    parent = conn.execute(
        "SELECT id, parent_id FROM todos WHERE id = ?", (dest_parent,)
    ).fetchone()
    if parent is None:
        raise TodoOrderError(f"parent todo {dest_parent} not found")
    if parent["parent_id"] is not None:
        raise TodoOrderError("subtask depth exceeds 2 levels")
    # 换父级才会多出一层；留在原父级下重排不算下沉。
    if dest_parent != current_parent:
        has_children = conn.execute(
            "SELECT 1 FROM todos WHERE parent_id = ? LIMIT 1", (todo_id,)
        ).fetchone()
        if has_children is not None:
            raise TodoOrderError("a todo with subtasks cannot become a subtask")


def move(
    conn: sqlite3.Connection,
    todo_id: int,
    position: str,
    reference_id: Optional[int] = None,
    target_parent_id: Any = INHERIT,
    now: str = "",
) -> Tuple[int, float]:
    """把 ``todo_id`` 移到目标位置，返回 ``(受影响行数, 新的 sort_order)``。

    所有合法性校验都在任何写库动作之前完成 —— 抛错时数据库没被动过。
    """
    if position not in ("before", "after"):
        raise TodoOrderError(f"invalid position: {position}")

    row = conn.execute(
        "SELECT id, parent_id FROM todos WHERE id = ?", (todo_id,)
    ).fetchone()
    if row is None:
        raise TodoOrderError(f"todo {todo_id} not found")
    current_parent = row["parent_id"]

    # 参照待办：必须存在、不能是自己，并决定目标层（未显式指定时）。
    ref_parent: Optional[int] = None
    if reference_id is not None:
        if reference_id == todo_id:
            raise TodoOrderError("a todo cannot reference itself")
        ref = conn.execute(
            "SELECT id, parent_id FROM todos WHERE id = ?", (reference_id,)
        ).fetchone()
        if ref is None:
            raise TodoOrderError(f"reference todo {reference_id} not found")
        ref_parent = ref["parent_id"]

    dest_parent = (
        ref_parent if isinstance(target_parent_id, _Inherit) else target_parent_id
    )

    _validate_dest_parent(conn, todo_id, current_parent, dest_parent)

    # 参照待办必须与目标层同层。
    if reference_id is not None and ref_parent != dest_parent:
        raise TodoOrderError("reference todo is not in the target layer")

    layer = _layer_rows(conn, dest_parent, exclude_id=todo_id)
    insert_at = _insert_index(layer, reference_id, position)
    prev_row = layer[insert_at - 1] if insert_at > 0 else None
    next_row = layer[insert_at] if insert_at < len(layer) else None

    new_order, exhausted = _midpoint(prev_row, next_row)
    if exhausted:
        # 浮点间距耗尽 → 整层重排：按目标次序重新以 SORT_STEP 为步长铺开。
        desired_ids = [item["id"] for item in layer]
        desired_ids.insert(insert_at, todo_id)
        for index, tid in enumerate(desired_ids):
            value = float((index + 1) * SORT_STEP)
            if tid == todo_id:
                conn.execute(
                    "UPDATE todos SET parent_id = ?, sort_order = ?, updated_at = ? "
                    "WHERE id = ?",
                    (dest_parent, value, now, tid),
                )
            else:
                conn.execute(
                    "UPDATE todos SET sort_order = ? WHERE id = ?", (value, tid)
                )
        return len(desired_ids), float((insert_at + 1) * SORT_STEP)

    conn.execute(
        "UPDATE todos SET parent_id = ?, sort_order = ?, updated_at = ? WHERE id = ?",
        (dest_parent, new_order, now, todo_id),
    )
    return 1, new_order
