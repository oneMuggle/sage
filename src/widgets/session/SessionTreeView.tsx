/**
 * A24 会话分支树可视化(移植自 pi 的 session branching)。
 *
 * 渲染会话分支树(对应后端 backend/domain/session_branch.py 的
 * SessionBranch 结构):
 * - 从根节点递归渲染,按深度缩进
 * - 高亮当前节点及其到根的路径(即当前分支)
 * - 分叉点显示分支数标记
 * - 点击节点 / Enter / Space 触发 onSwitchBranch(nodeId) 切换分支
 *
 * 纯展示组件:树状态由调用方(feature 层)管理,后续接入后端分支
 * API 与 useSessionBranch hook。
 */

/** 树节点数据(镜像后端 SessionNode) */
export interface SessionTreeNodeData {
  /** 节点唯一标识 */
  id: string;
  /** 父节点 id;null 表示根节点 */
  parentId: string | null;
  /** 节点对应的会话消息 id */
  messageId: string;
  /** 子节点 id 列表 */
  children: string[];
}

export interface SessionTreeViewProps {
  /** 节点表:nodeId → 节点 */
  nodes: Record<string, SessionTreeNodeData>;
  /** 根节点 id;null 表示空树 */
  rootNodeId: string | null;
  /** 当前游标所在节点 id */
  currentNodeId: string | null;
  /** 点击节点时调用(切换到该节点所在分支) */
  onSwitchBranch: (nodeId: string) => void;
}

/**
 * 计算从 startId 到根的节点集合(含两端),用于高亮当前分支。
 * 带环/悬空引用防御:异常数据时提前截断,不抛错(渲染层容错)。
 */
function computeCurrentPath(
  nodes: Record<string, SessionTreeNodeData>,
  startId: string | null,
): Set<string> {
  const path = new Set<string>();
  let current = startId;
  while (current !== null) {
    if (path.has(current)) break; // 环防御
    const node = nodes[current];
    if (!node) break; // 悬空父引用
    path.add(current);
    current = node.parentId;
  }
  return path;
}

interface TreeNodeItemProps {
  node: SessionTreeNodeData;
  depth: number;
  nodes: Record<string, SessionTreeNodeData>;
  currentPath: Set<string>;
  currentNodeId: string | null;
  onSwitchBranch: (nodeId: string) => void;
}

function TreeNodeItem({
  node,
  depth,
  nodes,
  currentPath,
  currentNodeId,
  onSwitchBranch,
}: TreeNodeItemProps) {
  const isCurrent = node.id === currentNodeId;
  const onCurrentBranch = currentPath.has(node.id);
  const branchCount = node.children.length;

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      onSwitchBranch(node.id);
    }
  };

  return (
    <div role="group">
      <div
        role="treeitem"
        tabIndex={0}
        aria-level={depth + 1}
        aria-selected={isCurrent}
        data-testid="session-tree-node"
        data-node-id={node.id}
        aria-label={`切换到消息 ${node.messageId}`}
        title={node.messageId}
        onClick={() => onSwitchBranch(node.id)}
        onKeyDown={handleKeyDown}
        style={{ paddingLeft: `${depth * 16 + 8}px` }}
        className={`
          flex items-center gap-1.5 py-1 pr-2 my-0.5 rounded-lg cursor-pointer text-sm
          transition-colors focus:outline-none focus:ring-2 focus:ring-primary
          ${
            isCurrent
              ? 'bg-primary/10 text-primary font-medium'
              : onCurrentBranch
                ? 'text-primary/80 hover:bg-bg-hover'
                : 'text-muted hover:bg-bg-hover'
          }
        `}
      >
        {branchCount > 1 && (
          <span
            data-testid="session-tree-fork"
            className="shrink-0 text-xs text-muted"
            title={`${branchCount} 个分支`}
          >
            ⑂ {branchCount}
          </span>
        )}
        <span className="truncate">{node.messageId}</span>
      </div>
      {node.children.map((childId) => {
        const child = nodes[childId];
        if (!child) return null; // 悬空子引用防御
        return (
          <TreeNodeItem
            key={childId}
            node={child}
            depth={depth + 1}
            nodes={nodes}
            currentPath={currentPath}
            currentNodeId={currentNodeId}
            onSwitchBranch={onSwitchBranch}
          />
        );
      })}
    </div>
  );
}

export function SessionTreeView({
  nodes,
  rootNodeId,
  currentNodeId,
  onSwitchBranch,
}: SessionTreeViewProps) {
  const root = rootNodeId !== null ? nodes[rootNodeId] : undefined;
  if (!root) {
    return (
      <div data-testid="session-tree-empty" className="px-3 py-4 text-xs text-muted text-center">
        暂无会话分支
      </div>
    );
  }

  const currentPath = computeCurrentPath(nodes, currentNodeId);

  return (
    <div role="tree" aria-label="会话分支树" data-testid="session-tree" className="session-tree">
      <TreeNodeItem
        node={root}
        depth={0}
        nodes={nodes}
        currentPath={currentPath}
        currentNodeId={currentNodeId}
        onSwitchBranch={onSwitchBranch}
      />
    </div>
  );
}
