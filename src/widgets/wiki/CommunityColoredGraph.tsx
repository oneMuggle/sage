// Community-Colored Graph View - 社区着色的知识图谱
// 基于 WikiGraphView，添加按社区着色的功能

import { useEffect, useState, useMemo } from 'react';

import { getWikiCommunities, type CommunityInfo } from '../../shared/api-client/wiki';
import type { GraphData } from '../../shared/types/wiki';

import { WikiGraphView } from './WikiGraphView';

// 社区调色板（12 种区分度高的颜色）
const COMMUNITY_PALETTE = [
  '#3b82f6', // blue-500
  '#10b981', // emerald-500
  '#f59e0b', // amber-500
  '#ef4444', // red-500
  '#8b5cf6', // violet-500
  '#ec4899', // pink-500
  '#06b6d4', // cyan-500
  '#84cc16', // lime-500
  '#f97316', // orange-500
  '#6366f1', // indigo-500
  '#14b8a6', // teal-500
  '#a855f7', // purple-500
];

interface CommunityColoredGraphProps {
  data: GraphData;
  query?: string;
  onNodeClick?: (pagePath: string) => void;
  projectPath?: string;
}

export function CommunityColoredGraph({
  data,
  query,
  onNodeClick,
  projectPath,
}: CommunityColoredGraphProps) {
  const [communities, setCommunities] = useState<CommunityInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedCommunity, setSelectedCommunity] = useState<number | null>(null);

  // 加载社区数据
  useEffect(() => {
    if (!projectPath) {
      setLoading(false);
      return;
    }

    setLoading(true);
    getWikiCommunities(projectPath)
      .then((response) => {
        setCommunities(response.communities);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, [projectPath]);

  // 构建节点 ID -> 社区 ID 的映射
  const nodeToCommunity = useMemo(() => {
    const map = new Map<string, number>();
    communities.forEach((c) => {
      c.members.forEach((memberId) => {
        map.set(memberId, c.community_id);
      });
    });
    return map;
  }, [communities]);

  // 为社区分配颜色
  const communityColors = useMemo(() => {
    const colors = new Map<number, string>();
    communities.forEach((c, idx) => {
      colors.set(c.community_id, COMMUNITY_PALETTE[idx % COMMUNITY_PALETTE.length]);
    });
    return colors;
  }, [communities]);

  // 过滤节点（如果选择了特定社区）
  const filteredData = useMemo(() => {
    if (selectedCommunity === null) return data;

    const allowedNodeIds = new Set(
      communities.find((c) => c.community_id === selectedCommunity)?.members || [],
    );

    return {
      nodes: data.nodes.filter((n) => allowedNodeIds.has(n.id)),
      edges: data.edges.filter((e) => allowedNodeIds.has(e.source) && allowedNodeIds.has(e.target)),
    };
  }, [data, communities, selectedCommunity]);

  // 加载中显示
  if (loading) {
    return (
      <div className="flex h-full items-center justify-center text-muted text-sm">
        加载社区数据...
      </div>
    );
  }

  return (
    <div className="relative w-full h-full">
      <WikiGraphView
        data={filteredData}
        query={query}
        onNodeClick={onNodeClick}
        nodeColorFn={(node) => {
          const communityId = nodeToCommunity.get(node.id);
          if (communityId !== undefined) {
            return communityColors.get(communityId) || '#94a3b8';
          }
          return '#94a3b8';
        }}
      />

      {/* 社区图例和过滤器 */}
      {communities.length > 0 && (
        <div
          className="absolute top-2 right-2 rounded-md border border-border bg-surface/95 p-3 text-xs shadow-sm max-h-96 overflow-y-auto"
          style={{ minWidth: 200 }}
        >
          <div className="mb-2 font-semibold flex items-center justify-between">
            <span>社区 ({communities.length})</span>
            {selectedCommunity !== null && (
              <button
                className="text-accent hover:underline"
                onClick={() => setSelectedCommunity(null)}
              >
                清除
              </button>
            )}
          </div>
          <div className="space-y-1">
            {communities.map((c) => {
              const color = communityColors.get(c.community_id) || '#94a3b8';
              const isSelected = selectedCommunity === c.community_id;
              return (
                <button
                  key={c.community_id}
                  className={`w-full flex items-center gap-2 px-2 py-1 rounded ${
                    isSelected ? 'bg-accent/10' : 'hover:bg-muted'
                  }`}
                  onClick={() => setSelectedCommunity(isSelected ? null : c.community_id)}
                >
                  <span
                    className="inline-block h-3 w-3 rounded-full flex-shrink-0"
                    style={{ background: color }}
                  />
                  <span className="flex-1 text-left">
                    社区 {c.community_id} ({c.size})
                  </span>
                  <span className="text-muted text-[10px]">{(c.cohesion * 100).toFixed(0)}%</span>
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
