// src/widgets/session/forkTree.ts
//
// W2（主流对标）：会话分叉家族树 —— 纯函数构建。
//
// 数据源：sessionApi.list()（每条 Session 自带 fork_root / forked_at_message_id，
// 见 session_repo.py M4）。给定当前会话，向上回溯到家族根，再收集全部后代，
// 供 ForkTreeModal 渲染层级树（对标 Claude Code 会话分支导航 / Cursor 分支切换）。

import type { Session } from '../../shared/api/types';

export interface ForkTreeNode {
  session: Session;
  /** 相对家族根的深度（根 = 0） */
  depth: number;
  /** 按分叉时间（created_at）排序的子节点 */
  children: ForkTreeNode[];
}

/**
 * 构建当前会话所在分叉家族的有序扁平列表（先根遍历，同层按创建时间升序）。
 *
 * 防御：fork_root 指向不存在会话（被删除/越权）时，以能追溯到的最深可达
 * 祖先为根；fork_root 成环时从当前会话截断成环边（数据异常兜底）。
 */
export function buildForkFamily(sessions: Session[], currentId: string): ForkTreeNode[] {
  const byId = new Map(sessions.map((s) => [s.id, s]));

  // 1) 向上找根：走 fork_root，记录访问集防环
  const current = byId.get(currentId);
  if (!current) return [];
  const visitedUp = new Set<string>([currentId]);
  let root = current;
  while (root.fork_root) {
    const parent = byId.get(root.fork_root);
    if (!parent || visitedUp.has(parent.id)) break; // 缺失或成环：到此为止
    visitedUp.add(parent.id);
    root = parent;
  }

  // 2) 从根收集整棵家族（BFS；成环边已不可能再进入——环上任一点向上必达 root，
  //    而 root 的下行构建只沿 children 前进，天然无环）
  const rootNode: ForkTreeNode = { session: root, depth: 0, children: [] };
  const nodeBySession = new Map<string, ForkTreeNode>([[root.id, rootNode]]);
  const queue: ForkTreeNode[] = [rootNode];
  while (queue.length > 0) {
    const node = queue.shift() as ForkTreeNode;
    const kids = sessions
      .filter((s) => s.fork_root === node.session.id && s.id !== root.id)
      .sort((a, b) => a.created_at - b.created_at);
    for (const kid of kids) {
      if (nodeBySession.has(kid.id)) continue; // 成环兜底
      const childNode: ForkTreeNode = {
        session: kid,
        depth: node.depth + 1,
        children: [],
      };
      node.children.push(childNode);
      nodeBySession.set(kid.id, childNode);
      queue.push(childNode);
    }
  }

  // 3) 先根遍历输出扁平列表（渲染直接顺序映射 + depth 缩进）
  const out: ForkTreeNode[] = [];
  const walk = (node: ForkTreeNode): void => {
    out.push(node);
    for (const child of node.children) walk(child);
  };
  walk(rootNode);
  return out;
}
