/**
 * useTodoDrag — 待办拖拽排序 / 拖拽嵌套的交互状态（P1）。
 *
 * 职责边界:
 *   - 本文件只管「拖拽过程」的状态：谁正被拖、当前落点落在哪一区、落点是否合法；
 *   - 落点计算 / 请求构造 / 乐观重排等纯逻辑在 ``shared/lib/dnd/todoDrag.ts``；
 *   - 真正的落库请求由 ``entities/todo/todoStore`` 的 ``moveTodo`` 负责。
 *
 * 视图约定:
 *   - 只有「手动排序」（``enabled``）时才允许拖动，否则拖柄禁用并说明原因；
 *   - ``sameLayerOnly``（树形视图）：「前 / 后」落区只允许同层重排；
 *   - ``allowNest``：允许「变成子任务」落区 —— 目标必须是**顶层**行，
 *     且被拖行不能已经带子任务（层级上限两层，与方案 §3.3 一致）。
 *
 * 对方案 §3.5 的修订:
 *   原方案把「嵌套」限定在扁平列表视图。但扁平列表只在**完全没有子任务**时
 *   才出现（TodoPage 按 ``hasSubtasks`` 二选一渲染），一旦嵌套出第一个子任务
 *   就切到树形视图 —— 那样嵌套会变成「只能用一次」的死路。
 *   因此本实现让两种视图都支持「变成子任务」，树形视图仍对「前 / 后」保持
 *   同层限制。层级约束（两层）未放宽。
 */
import { useCallback, useMemo, useRef, useState } from 'react';
import type { DragEvent } from 'react';

import type { Todo, TodoDropZone } from '../../shared/api/types';
import { canNestInto, computeDropZone, isValidDropTarget } from '../../shared/lib/dnd/todoDrag';

/** 拖柄的绑定 —— 挂在行末的 GripVertical 按钮上。 */
export interface TodoDragHandleBinding {
  /** 是否允许拖起（仅「手动排序」为真）。 */
  draggable: boolean;
  /** 悬浮提示：禁用时说明原因，避免「拖了没反应」。 */
  title: string;
  onDragStart: (event: DragEvent<HTMLElement>) => void;
  onDragEnd: () => void;
}

/** 行本身的绑定 —— 挂在待办行的 ``li`` 上。 */
export interface TodoDragRowBinding {
  /** 该行正被拖起（半透明）。 */
  isDragging: boolean;
  /** 该行当前作为落点的区域；null 表示当前不是落点。 */
  dropZone: TodoDropZone | null;
  onDragOver: (event: DragEvent<HTMLElement>) => void;
  onDragLeave: (event: DragEvent<HTMLElement>) => void;
  onDrop: (event: DragEvent<HTMLElement>) => void;
}

export interface UseTodoDragOptions {
  todos: Todo[];
  /** 是否允许拖动（仅「手动排序」为真）。 */
  enabled: boolean;
  /** 是否提供「变成子任务」落区。 */
  allowNest: boolean;
  /** 「前 / 后」落区是否只允许同层（树形视图）。 */
  sameLayerOnly: boolean;
  onMove: (draggedId: number, targetId: number, zone: TodoDropZone) => void | Promise<void>;
}

export interface UseTodoDragResult {
  handleFor: (todo: Todo) => TodoDragHandleBinding;
  rowFor: (todo: Todo) => TodoDragRowBinding;
  /** 正在被拖动的待办 id（null = 当前没有拖拽）。 */
  draggingId: number | null;
}

/** 拖拽影像相对行左上角的偏移（让浮起的幽灵行大致对齐指针）。 */
const DRAG_IMAGE_OFFSET_X = 24;
const DRAG_IMAGE_OFFSET_Y = 14;

export function useTodoDrag(options: UseTodoDragOptions): UseTodoDragResult {
  const { todos, enabled, allowNest, sameLayerOnly, onMove } = options;

  const [draggingId, setDraggingId] = useState<number | null>(null);
  const [dropTarget, setDropTarget] = useState<{ id: number; zone: TodoDropZone } | null>(null);

  // 事件回调里读到的是「最近一次」的值；state 闭包可能滞后（一次拖拽内
  // dragover 会连发几十次），所以另用 ref 兜底。
  const draggingIdRef = useRef<number | null>(null);
  const dropTargetRef = useRef<{ id: number; zone: TodoDropZone } | null>(null);

  const todoById = useMemo(() => {
    const map = new Map<number, Todo>();
    for (const todo of todos) map.set(todo.id, todo);
    return map;
  }, [todos]);

  /** 哪些待办已经带子任务 —— 带子任务的行不能再被拖成别人的子任务（会超两层）。 */
  const parentIds = useMemo(() => {
    const ids = new Set<number>();
    for (const todo of todos) {
      if (todo.parent_id != null) ids.add(todo.parent_id);
    }
    return ids;
  }, [todos]);

  const clearDragState = useCallback(() => {
    draggingIdRef.current = null;
    dropTargetRef.current = null;
    setDraggingId(null);
    setDropTarget(null);
  }, []);

  const handleFor = useCallback(
    (todo: Todo): TodoDragHandleBinding => ({
      draggable: enabled,
      title: enabled ? '拖动调整顺序（拖到行左侧可变成子任务）' : '仅「手动排序」下可拖动调整顺序',
      onDragStart: (event) => {
        if (!enabled) {
          event.preventDefault();
          return;
        }
        event.dataTransfer.effectAllowed = 'move';
        // Firefox 要求 dragstart 必须写入数据，否则不会开始拖拽。
        event.dataTransfer.setData('text/plain', String(todo.id));
        // 幽灵影像用整行，而不是只画一个小把手。
        const row = event.currentTarget.closest('li');
        if (row instanceof HTMLElement) {
          event.dataTransfer.setDragImage(row, DRAG_IMAGE_OFFSET_X, DRAG_IMAGE_OFFSET_Y);
        }
        draggingIdRef.current = todo.id;
        dropTargetRef.current = null;
        setDraggingId(todo.id);
        setDropTarget(null);
      },
      onDragEnd: () => clearDragState(),
    }),
    [enabled, clearDragState],
  );

  const rowFor = useCallback(
    (todo: Todo): TodoDragRowBinding => ({
      isDragging: draggingId === todo.id,
      dropZone: dropTarget?.id === todo.id ? dropTarget.zone : null,
      onDragOver: (event) => {
        const draggedId = draggingIdRef.current;
        if (!enabled || draggedId === null) return;
        const dragged = todoById.get(draggedId);
        if (!dragged) return;
        // 拖到自己身上没有意义。
        if (dragged.id === todo.id) return;

        // 「变成子任务」只在目标为顶层行、且被拖行没有子任务时可用。
        const nestAllowed = allowNest && canNestInto(dragged, todo, parentIds.has(dragged.id));

        const rect = event.currentTarget.getBoundingClientRect();
        const zone = computeDropZone(event.clientX, rect, nestAllowed);

        // 「前 / 后」在树形视图下必须同层；「变成子任务」是跨层落点，
        // 它自己的合法性已由 canNestInto 保证。
        const valid =
          zone === 'inside'
            ? nestAllowed
            : isValidDropTarget(dragged, todo, { allowNest: nestAllowed, sameLayerOnly });

        if (!valid) {
          // 不 preventDefault —— 浏览器就不会接受 drop，光标显示「禁止」。
          if (dropTargetRef.current?.id === todo.id) {
            dropTargetRef.current = null;
            setDropTarget(null);
          }
          return;
        }

        event.preventDefault();
        event.dataTransfer.dropEffect = 'move';
        if (dropTargetRef.current?.id === todo.id && dropTargetRef.current.zone === zone) return;
        dropTargetRef.current = { id: todo.id, zone };
        setDropTarget({ id: todo.id, zone });
      },
      onDragLeave: (event) => {
        const related = event.relatedTarget;
        // 移到行内别的子元素上时也会触发 dragleave —— 别急着清指示线。
        if (related instanceof Node && event.currentTarget.contains(related)) return;
        if (dropTargetRef.current?.id === todo.id) {
          dropTargetRef.current = null;
          setDropTarget(null);
        }
      },
      onDrop: (event) => {
        event.preventDefault();
        const dragged = draggingIdRef.current;
        const current = dropTargetRef.current;
        clearDragState();
        if (dragged === null || !current || current.id !== todo.id) return;
        void onMove(dragged, todo.id, current.zone);
      },
    }),
    [
      draggingId,
      dropTarget,
      todoById,
      parentIds,
      enabled,
      allowNest,
      sameLayerOnly,
      clearDragState,
      onMove,
    ],
  );

  return { handleFor, rowFor, draggingId };
}
