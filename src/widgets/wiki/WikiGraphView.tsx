// Wiki Graph View - React Flow 渲染知识图谱（参考 llm_wiki 优化）
//
// 设计要点:
// - 用 @xyflow/react 渲染节点 + 边
// - 节点按 type 颜色,边按 signal 类型 + weight 粗细
// - 节点大小根据 wikilinks 数量动态计算
// - 悬停效果：高亮当前节点和邻居节点
// - 搜索框 → 输入 query → 高亮相关节点
// - 布局：使用圆形/辐射布局（比网格更美观）
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  type Node,
  type Edge,
  type NodeProps,
  Handle,
  Position,
  useNodesState,
  useEdgesState,
} from '@xyflow/react';
import { useMemo, useState } from 'react';
import '@xyflow/react/dist/style.css';

import type { GraphData, GraphSignal } from '../../shared/types/wiki';

// ============================================================================
// 类型
// ============================================================================

interface WikiNodeData extends Record<string, unknown> {
  label: string;
  pageType?: string;
  sourceCount: number;
  wikilinkCount: number;
  highlighted: boolean;
  hovered: boolean;
  isNeighbor: boolean;
}

interface WikiGraphViewProps {
  data: GraphData;
  query?: string;
  onNodeClick?: (pagePath: string) => void;
}

// ============================================================================
// 颜色映射
// ============================================================================

const TYPE_COLORS: Record<string, string> = {
  entity: '#60a5fa', // blue-400
  concept: '#c084fc', // purple-400
  source: '#fb923c', // orange-400
  query: '#4ade80', // green-400
  synthesis: '#f87171', // red-400
  overview: '#facc15', // yellow-400
  comparison: '#2dd4bf', // teal-400
  finding: '#a855f7', // purple-500
  thesis: '#f43f5e', // rose-500
  methodology: '#14b8a6', // teal-500
  default: '#94a3b8', // slate-400
};

const SIGNAL_COLORS: Record<GraphSignal, string> = {
  DirectLink: '#0ea5e9',
  SourceOverlap: '#a855f7',
  TypeAffinity: '#94a3b8',
};

const BASE_NODE_SIZE = 40;
const MAX_NODE_SIZE = 80;

/**
 * @internal
 * Exported for unit tests in `__tests__/WikiGraphView.test.tsx`.
 * Not part of the public widget API — do not import from feature/app code.
 */
// eslint-disable-next-line react-refresh/only-export-components
export function colorByType(pageType?: string): string {
  if (!pageType) return TYPE_COLORS.default;
  return TYPE_COLORS[pageType] ?? TYPE_COLORS.default;
}

function nodeSizeByLinks(wikilinkCount: number, maxLinks: number): number {
  if (maxLinks === 0) return BASE_NODE_SIZE;
  const ratio = wikilinkCount / maxLinks;
  return BASE_NODE_SIZE + Math.sqrt(ratio) * (MAX_NODE_SIZE - BASE_NODE_SIZE);
}

// ============================================================================
// 自定义节点组件
// ============================================================================

function WikiNode({ data }: NodeProps<Node<WikiNodeData>>) {
  const d = data;
  const color = colorByType(d.pageType);
  const size = nodeSizeByLinks(d.wikilinkCount, 10); // 简化：假设 maxLinks=10
  const isActive = d.highlighted && (d.hovered || d.isNeighbor);

  return (
    <div
      style={{
        background: isActive ? color : '#1e293b',
        border: `2px solid ${color}`,
        borderRadius: '50%', // 圆形节点
        padding: '8px 12px',
        width: size,
        height: size,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        color: isActive ? '#0f172a' : '#f1f5f9',
        fontSize: 11,
        fontWeight: d.hovered ? 700 : d.highlighted ? 500 : 400,
        opacity: d.highlighted ? 1 : 0.3,
        transition: 'all 0.2s ease',
        cursor: 'pointer',
        boxShadow: d.hovered ? `0 0 12px ${color}` : 'none',
      }}
      title={`${d.label}\nType: ${d.pageType ?? 'unknown'}\nSources: ${d.sourceCount}\nLinks: ${d.wikilinkCount}`}
    >
      <Handle type="target" position={Position.Top} style={{ background: color, opacity: 0 }} />
      <div style={{ fontWeight: 'bold', fontSize: 12, textAlign: 'center', lineHeight: 1.2 }}>
        {d.label}
      </div>
      <div style={{ fontSize: 9, opacity: 0.8, marginTop: 2 }}>{d.wikilinkCount} links</div>
      <Handle type="source" position={Position.Bottom} style={{ background: color, opacity: 0 }} />
    </div>
  );
}

const nodeTypes = { wiki: WikiNode };

// ============================================================================
// 布局算法（圆形布局）
// ============================================================================

function circularLayout(nodeCount: number): Map<string, { x: number; y: number }> {
  const positions = new Map<string, { x: number; y: number }>();
  const centerX = 0;
  const centerY = 0;
  const radius = Math.max(300, nodeCount * 30); // 半径根据节点数动态计算

  for (let i = 0; i < nodeCount; i++) {
    const angle = (i / nodeCount) * 2 * Math.PI;
    const x = centerX + radius * Math.cos(angle);
    const y = centerY + radius * Math.sin(angle);
    positions.set(`node-${i}`, { x, y });
  }

  return positions;
}

// ============================================================================
// 组件
// ============================================================================

export function WikiGraphView({ data, query, onNodeClick }: WikiGraphViewProps) {
  const [hoveredNodeId, setHoveredNodeId] = useState<string | null>(null);

  const {
    nodes: initialNodes,
    edges: initialEdges,
    matchedIds,
  } = useMemo(() => buildGraph(data, query), [data, query]);

  // 计算当前悬停节点的邻居
  const currentNeighborIds = useMemo(() => {
    if (!hoveredNodeId) return new Set<string>();
    const neighbors = new Set<string>();
    data.edges.forEach((e) => {
      if (e.source === hoveredNodeId) neighbors.add(e.target);
      if (e.target === hoveredNodeId) neighbors.add(e.source);
    });
    return neighbors;
  }, [hoveredNodeId, data.edges]);

  // 更新节点状态以反映悬停
  const nodesWithHover = useMemo(() => {
    return initialNodes.map((node) => ({
      ...node,
      data: {
        ...node.data,
        hovered: node.id === hoveredNodeId,
        isNeighbor: currentNeighborIds.has(node.id),
      },
    }));
  }, [initialNodes, hoveredNodeId, currentNeighborIds]);

  // 更新边的状态
  const edgesWithHover = useMemo(() => {
    return initialEdges.map((edge) => {
      const isHighlighted =
        hoveredNodeId && (edge.source === hoveredNodeId || edge.target === hoveredNodeId);
      return {
        ...edge,
        style: {
          ...edge.style,
          opacity: hoveredNodeId ? (isHighlighted ? 1 : 0.2) : 0.6,
          strokeWidth: isHighlighted ? 3 : 1.5,
        },
      };
    });
  }, [initialEdges, hoveredNodeId]);

  const [nodes, setNodes, onNodesChange] = useNodesState(nodesWithHover);
  const [edges, setEdges, onEdgesChange] = useEdgesState(edgesWithHover);

  // 当悬停状态变化时更新节点
  useMemo(() => {
    setNodes(nodesWithHover);
    setEdges(edgesWithHover);
  }, [nodesWithHover, edgesWithHover, setNodes, setEdges]);

  if (data.nodes.length === 0) {
    return (
      <div className="flex h-full items-center justify-center text-muted text-sm">
        暂无 wiki 页面。先创建或导入一些 wiki 页面。
      </div>
    );
  }

  return (
    <div style={{ width: '100%', height: '100%' }} data-testid="wiki-graph-view">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeClick={(_, n) => {
          if (onNodeClick) onNodeClick(n.id);
        }}
        onNodeMouseEnter={(_, node) => setHoveredNodeId(node.id)}
        onNodeMouseLeave={() => setHoveredNodeId(null)}
        fitView
        fitViewOptions={{ padding: 0.2 }}
        proOptions={{ hideAttribution: true }}
        defaultEdgeOptions={{
          style: { stroke: '#64748b', strokeWidth: 1.5 },
        }}
      >
        <Background color="#334155" gap={20} />
        <Controls />
        <MiniMap
          pannable
          zoomable
          nodeColor={(node) => {
            const nodeData = node.data as WikiNodeData;
            return colorByType(nodeData.pageType);
          }}
          maskColor="rgba(0, 0, 0, 0.6)"
        />
      </ReactFlow>
      <Legend matchedCount={matchedIds.size} totalCount={data.nodes.length} />
      <Stats nodeCount={data.nodes.length} edgeCount={data.edges.length} />
    </div>
  );
}

// ============================================================================
// 布局 + 边/节点构建
// ============================================================================

/**
 * @internal
 * Exported for unit tests in `__tests__/WikiGraphView.test.tsx`.
 * Not part of the public widget API — do not import from feature/app code.
 */
// eslint-disable-next-line react-refresh/only-export-components
export function buildGraph(
  data: GraphData,
  query?: string,
): {
  nodes: Node<WikiNodeData>[];
  edges: Edge[];
  matchedIds: Set<string>;
  neighborIds: Set<string>;
} {
  const matchedIds = computeMatchedIds(data, query);

  // 计算每个节点的连接数（用于动态大小）
  const linkCounts = new Map<string, number>();
  data.edges.forEach((e) => {
    linkCounts.set(e.source, (linkCounts.get(e.source) ?? 0) + 1);
    linkCounts.set(e.target, (linkCounts.get(e.target) ?? 0) + 1);
  });

  // 圆形布局
  const positions = circularLayout(data.nodes.length);

  const nodes: Node<WikiNodeData>[] = data.nodes.map((n, i) => ({
    id: n.id,
    type: 'wiki',
    data: {
      label: n.label,
      pageType: n.page_type,
      sourceCount: n.sources.length,
      wikilinkCount: linkCounts.get(n.id) ?? n.wikilinks.length,
      highlighted: matchedIds.size === 0 || matchedIds.has(n.id),
      hovered: false,
      isNeighbor: false,
    },
    position: positions.get(`node-${i}`) ?? { x: 0, y: 0 },
  }));

  const edges: Edge[] = data.edges.map((e, i) => ({
    id: `${e.source}->${e.target}-${e.signal}-${i}`,
    source: e.source,
    target: e.target,
    label: e.signal,
    style: {
      stroke: SIGNAL_COLORS[e.signal] ?? '#94a3b8',
      strokeWidth: Math.max(1, e.weight / 2),
      opacity: 0.6,
    },
    animated: e.signal === 'DirectLink',
  }));

  return { nodes, edges, matchedIds, neighborIds: new Set() };
}

function computeMatchedIds(data: GraphData, query?: string): Set<string> {
  if (!query || !query.trim()) return new Set();
  const q = query.toLowerCase();
  return new Set(
    data.nodes
      .filter(
        (n) =>
          n.label.toLowerCase().includes(q) ||
          n.id.toLowerCase().includes(q) ||
          (n.page_type?.toLowerCase().includes(q) ?? false),
      )
      .map((n) => n.id),
  );
}

// ============================================================================
// 图例
// ============================================================================

function Legend({ matchedCount, totalCount }: { matchedCount: number; totalCount: number }) {
  return (
    <div
      className="absolute top-2 right-2 rounded-md border border-border bg-surface/95 p-3 text-xs shadow-sm"
      style={{ minWidth: 180 }}
    >
      <div className="mb-2 font-semibold">图例</div>
      <div className="mb-2 text-muted">
        {matchedCount > 0 ? `匹配 ${matchedCount} / ${totalCount} 节点` : `共 ${totalCount} 节点`}
      </div>
      <div className="space-y-1">
        <div className="font-semibold mt-2">节点类型</div>
        {Object.entries(TYPE_COLORS).map(([t, c]) => (
          <div key={t} className="flex items-center gap-2">
            <span className="inline-block h-3 w-3 rounded-full" style={{ background: c }} />
            <span>{t}</span>
          </div>
        ))}
        <div className="font-semibold mt-2">边类型</div>
        {Object.entries(SIGNAL_COLORS).map(([s, c]) => (
          <div key={s} className="flex items-center gap-2">
            <span className="inline-block h-0.5 w-6" style={{ background: c }} />
            <span>{s}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function Stats({ nodeCount, edgeCount }: { nodeCount: number; edgeCount: number }) {
  return (
    <div className="absolute bottom-2 left-2 rounded-md border border-border bg-surface/95 px-3 py-2 text-xs shadow-sm">
      <span className="font-semibold">统计：</span>
      <span className="ml-2">{nodeCount} 节点</span>
      <span className="ml-2">{edgeCount} 边</span>
    </div>
  );
}

// Tests for colorByType / buildGraph helpers live in
// ./__tests__/WikiGraphView.test.tsx (co-located test pattern).
// Do not reintroduce top-level `describe()` blocks in this file — Vite's dep
// optimizer executes module top-level code in the browser dev server, where
// vitest's initSuite throws because the test runner config is unavailable.
