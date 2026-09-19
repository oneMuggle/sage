/**
 * 任务树索引（spec 2026-09-19 §前端设计）。
 *
 * 把平铺的 plan（可选 parent_task_id/depth）转成渲染顺序 + 深度 + 子节点关系。
 * 规则：
 * - parent 找不到（或缺失）→ 该任务降级为根节点，**不丢弃**；
 * - 深度按父链实际层级计算并钳制上限，避免脏数据炸缩进；
 * - 顺序保持原计划顺序（稳定的先序 DFS）。
 */
import type { TaskPlanItem } from '../../../shared/api/types';

export interface TaskTreeNode {
  item: TaskPlanItem;
  /** 渲染缩进层级（0 = 根）。 */
  depth: number;
  /** 直接子任务的 task_id（保持计划顺序）。 */
  childIds: string[];
}

export interface TaskTreeIndex {
  /** 树的根节点（保持计划顺序）。 */
  roots: string[];
  nodes: Map<string, TaskTreeNode>;
}

const MAX_RENDER_DEPTH = 8;

export function buildTaskTree(plan: TaskPlanItem[]): TaskTreeIndex {
  const nodes = new Map<string, TaskTreeNode>();
  const ids = new Set(plan.map((item) => item.task_id));

  for (const item of plan) {
    nodes.set(item.task_id, { item, depth: 0, childIds: [] });
  }

  const roots: string[] = [];
  for (const item of plan) {
    const parentId = item.parent_task_id ?? null;
    // 父不存在 / 自指 / 缺失 → 降级为根（容错渲染，不丢任务）。
    if (parentId && parentId !== item.task_id && ids.has(parentId)) {
      nodes.get(parentId)!.childIds.push(item.task_id);
    } else {
      roots.push(item.task_id);
    }
  }

  // 先序 DFS 赋深度，同时断开异常环（防御：父链成环时不再递归）。
  const visited = new Set<string>();
  const walk = (id: string, depth: number) => {
    if (visited.has(id)) return;
    visited.add(id);
    const node = nodes.get(id)!;
    node.depth = Math.min(depth, MAX_RENDER_DEPTH);
    for (const childId of node.childIds) {
      walk(childId, node.depth + 1);
    }
  };
  for (const rootId of roots) {
    walk(rootId, 0);
  }
  // 环中节点未被 roots 触及 → 兜底按根渲染，保证全部任务可见。
  for (const item of plan) {
    if (!visited.has(item.task_id)) {
      roots.push(item.task_id);
      walk(item.task_id, 0);
    }
  }

  return { roots, nodes };
}

/** 某节点折叠时应隐藏的全部后代 task_id。 */
export function descendantsOf(index: TaskTreeIndex, taskId: string): string[] {
  const out: string[] = [];
  const stack = [...(index.nodes.get(taskId)?.childIds ?? [])];
  while (stack.length > 0) {
    const current = stack.pop()!;
    out.push(current);
    stack.push(...(index.nodes.get(current)?.childIds ?? []));
  }
  return out;
}

/** 先序展开为渲染顺序（父在子前）。 */
export function flattenTree(index: TaskTreeIndex): TaskTreeNode[] {
  const out: TaskTreeNode[] = [];
  const walk = (id: string) => {
    const node = index.nodes.get(id);
    if (!node) return;
    out.push(node);
    for (const childId of node.childIds) {
      walk(childId);
    }
  };
  for (const rootId of index.roots) {
    walk(rootId);
  }
  return out;
}
