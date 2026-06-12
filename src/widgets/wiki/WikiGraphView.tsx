// Wiki Graph View - React Flow 渲染 4-signal 知识图谱
//
// 设计要点:
// - 用 @xyflow/react 渲染节点 + 边
// - 节点按 type 颜色,边按 signal 类型 + weight 粗细
// - 节点 click → 调 onNodeClick 回调(切到 browser view 打开文件)
// - 搜索框 → 输入 query → 高亮相关节点(浅色背景)
// - 简化布局:用 id 哈希到固定网格位置(无 dagre,后续 Phase 可加)
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
} from '@xyflow/react';
import { useMemo } from 'react';
import '@xyflow/react/dist/style.css';
import { describe, it, expect } from 'vitest';

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
  source: '#3b82f6', // 蓝
  entity: '#8b5cf6', // 紫
  concept: '#10b981', // 绿
  query: '#f59e0b', // 黄
  synthesis: '#ef4444', // 红
  default: '#94a3b8', // 灰
};

const SIGNAL_COLORS: Record<GraphSignal, string> = {
  DirectLink: '#0ea5e9',
  SourceOverlap: '#a855f7',
  TypeAffinity: '#94a3b8',
};

function colorByType(pageType?: string): string {
  if (!pageType) return TYPE_COLORS.default;
  return TYPE_COLORS[pageType] ?? TYPE_COLORS.default;
}

// ============================================================================
// 自定义节点组件
// ============================================================================

function WikiNode({ data }: NodeProps<Node<WikiNodeData>>) {
  const d = data;
  const color = colorByType(d.pageType);
  return (
    <div
      style={{
        background: d.highlighted ? color : '#1e293b',
        border: `2px solid ${color}`,
        borderRadius: 8,
        padding: '8px 12px',
        minWidth: 120,
        color: d.highlighted ? '#0f172a' : '#f1f5f9',
        fontSize: 12,
        fontWeight: d.highlighted ? 600 : 400,
        opacity: d.highlighted ? 1 : 0.7,
        transition: 'all 0.2s',
      }}
      title={`${d.label}\nType: ${d.pageType ?? 'unknown'}\nSources: ${d.sourceCount}\nLinks: ${d.wikilinkCount}`}
    >
      <Handle type="target" position={Position.Top} style={{ background: color }} />
      <div style={{ fontWeight: 'bold' }}>{d.label}</div>
      <div style={{ fontSize: 10, opacity: 0.8, marginTop: 4 }}>
        {d.pageType ?? 'unknown'} · {d.wikilinkCount} links
      </div>
      <Handle type="source" position={Position.Bottom} style={{ background: color }} />
    </div>
  );
}

const nodeTypes = { wiki: WikiNode };

// ============================================================================
// 组件
// ============================================================================

export function WikiGraphView({ data, query, onNodeClick }: WikiGraphViewProps) {
  const { nodes, edges, matchedIds } = useMemo(() => buildGraph(data, query), [data, query]);

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
        onNodeClick={(_, n) => {
          if (onNodeClick) onNodeClick(n.id);
        }}
        fitView
        proOptions={{ hideAttribution: true }}
      >
        <Background />
        <Controls />
        <MiniMap pannable zoomable />
      </ReactFlow>
      <Legend matchedCount={matchedIds.size} totalCount={data.nodes.length} />
    </div>
  );
}

// ============================================================================
// 布局 + 边/节点构建
// ============================================================================

function buildGraph(
  data: GraphData,
  query?: string,
): { nodes: Node<WikiNodeData>[]; edges: Edge[]; matchedIds: Set<string> } {
  const matchedIds = computeMatchedIds(data, query);

  // 简易网格布局:按 id 哈希到 (col, row)
  const cols = Math.max(1, Math.ceil(Math.sqrt(data.nodes.length)));
  const positions = new Map<string, { x: number; y: number }>();
  data.nodes.forEach((n, i) => {
    const col = i % cols;
    const row = Math.floor(i / cols);
    positions.set(n.id, { x: col * 220, y: row * 120 });
  });

  const nodes: Node<WikiNodeData>[] = data.nodes.map((n) => ({
    id: n.id,
    type: 'wiki',
    data: {
      label: n.label,
      pageType: n.page_type,
      sourceCount: n.sources.length,
      wikilinkCount: n.wikilinks.length,
      highlighted: matchedIds.size === 0 || matchedIds.has(n.id),
    },
    position: positions.get(n.id) ?? { x: 0, y: 0 },
  }));

  const edges: Edge[] = data.edges.map((e, i) => ({
    id: `${e.source}->${e.target}-${e.signal}-${i}`,
    source: e.source,
    target: e.target,
    label: e.signal,
    style: {
      stroke: SIGNAL_COLORS[e.signal] ?? '#94a3b8',
      strokeWidth: Math.max(1, e.weight / 2),
    },
    animated: e.signal === 'DirectLink',
  }));

  return { nodes, edges, matchedIds };
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
            <span className="inline-block h-3 w-3 rounded-sm" style={{ background: c }} />
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

// ============================================================================
// Tests
// ============================================================================

describe('WikiGraphView helpers', () => {
  it('colorByType returns default for unknown', () => {
    expect(colorByType(undefined)).toBe(TYPE_COLORS.default);
    expect(colorByType('unknown_type')).toBe(TYPE_COLORS.default);
  });

  it('colorByType returns mapped color', () => {
    expect(colorByType('source')).toBe(TYPE_COLORS.source);
    expect(colorByType('entity')).toBe(TYPE_COLORS.entity);
  });

  it('buildGraph produces nodes and edges from GraphData', () => {
    const data: GraphData = {
      nodes: [
        {
          id: 'a',
          label: 'A',
          page_type: 'source',
          sources: ['x.pdf'],
          wikilinks: [],
        },
        {
          id: 'b',
          label: 'B',
          page_type: 'concept',
          sources: [],
          wikilinks: [],
        },
      ],
      edges: [{ source: 'a', target: 'b', signal: 'DirectLink', weight: 3.0 }],
    };
    const { nodes, edges } = buildGraph(data);
    expect(nodes).toHaveLength(2);
    expect(edges).toHaveLength(1);
    expect(nodes[0].data.highlighted).toBe(true);
  });

  it('buildGraph dims non-matching nodes when query set', () => {
    const data: GraphData = {
      nodes: [
        { id: 'a', label: 'Albert', page_type: 'entity', sources: [], wikilinks: [] },
        { id: 'b', label: 'Other', page_type: 'entity', sources: [], wikilinks: [] },
      ],
      edges: [],
    };
    const { nodes, matchedIds } = buildGraph(data, 'albert');
    expect(matchedIds.has('a')).toBe(true);
    expect(matchedIds.has('b')).toBe(false);
    expect(nodes[0].data.highlighted).toBe(true);
    expect(nodes[1].data.highlighted).toBe(false);
  });

  it('buildGraph case-insensitive matching', () => {
    const data: GraphData = {
      nodes: [{ id: 'a', label: 'ALBERT', page_type: 'entity', sources: [], wikilinks: [] }],
      edges: [],
    };
    const { matchedIds } = buildGraph(data, 'albert');
    expect(matchedIds.has('a')).toBe(true);
  });

  it('buildGraph matches by id (file path)', () => {
    const data: GraphData = {
      nodes: [{ id: 'wiki/sources/albert.md', label: 'X', sources: [], wikilinks: [] }],
      edges: [],
    };
    const { matchedIds } = buildGraph(data, 'albert');
    expect(matchedIds.has('wiki/sources/albert.md')).toBe(true);
  });
});
