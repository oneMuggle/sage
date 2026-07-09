// Wiki Insights Panel - 显示图谱洞察（惊人联系 + 知识缺口）
import { useEffect, useState } from 'react';

import {
  getWikiInsights,
  type InsightsResponse,
  type SurprisingConnection,
  type KnowledgeGap,
} from '../../shared/api-client/wiki';

interface WikiInsightsPanelProps {
  projectPath: string;
  onNodeClick?: (pagePath: string) => void;
}

export function WikiInsightsPanel({ projectPath, onNodeClick }: WikiInsightsPanelProps) {
  const [insights, setInsights] = useState<InsightsResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!projectPath) return;

    setLoading(true);
    setError(null);

    getWikiInsights(projectPath)
      .then(setInsights)
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, [projectPath]);

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center text-muted text-sm">
        分析图谱中...
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex h-full items-center justify-center text-destructive text-sm">
        加载失败: {error}
      </div>
    );
  }

  if (!insights) {
    return null;
  }

  return (
    <div className="h-full overflow-y-auto p-4 space-y-6">
      {/* Stats */}
      <div className="grid grid-cols-2 gap-3">
        <StatCard label="节点" value={insights.stats.total_nodes} />
        <StatCard label="边" value={insights.stats.total_edges} />
        <StatCard label="社区" value={insights.stats.total_communities} />
        <StatCard label="惊人联系" value={insights.stats.surprising_connections} highlight />
      </div>

      {/* Surprising Connections */}
      {insights.surprising_connections.length > 0 && (
        <section>
          <h3 className="text-sm font-semibold mb-3 flex items-center gap-2">
            <span className="text-lg">✨</span>
            惊人联系 ({insights.surprising_connections.length})
          </h3>
          <div className="space-y-2">
            {insights.surprising_connections.slice(0, 10).map((conn, i) => (
              <SurprisingConnectionCard key={i} connection={conn} onNodeClick={onNodeClick} />
            ))}
          </div>
        </section>
      )}

      {/* Knowledge Gaps */}
      {insights.knowledge_gaps.length > 0 && (
        <section>
          <h3 className="text-sm font-semibold mb-3 flex items-center gap-2">
            <span className="text-lg">🔍</span>
            知识缺口 ({insights.knowledge_gaps.length})
          </h3>
          <div className="space-y-2">
            {insights.knowledge_gaps.slice(0, 10).map((gap, i) => (
              <KnowledgeGapCard key={i} gap={gap} onNodeClick={onNodeClick} />
            ))}
          </div>
        </section>
      )}

      {/* Empty state */}
      {insights.surprising_connections.length === 0 && insights.knowledge_gaps.length === 0 && (
        <div className="flex flex-col items-center justify-center h-64 text-muted text-sm">
          <span className="text-4xl mb-2">🎉</span>
          <div>图谱结构良好，暂无发现</div>
        </div>
      )}
    </div>
  );
}

// ============================================================================
// 子组件
// ============================================================================

function StatCard({
  label,
  value,
  highlight = false,
}: {
  label: string;
  value: number;
  highlight?: boolean;
}) {
  return (
    <div
      className={`rounded-md border p-3 ${
        highlight ? 'border-accent bg-accent/10' : 'border-border bg-surface'
      }`}
    >
      <div className="text-xs text-muted">{label}</div>
      <div className={`text-2xl font-bold ${highlight ? 'text-accent' : ''}`}>{value}</div>
    </div>
  );
}

function SurprisingConnectionCard({
  connection,
  onNodeClick,
}: {
  connection: SurprisingConnection;
  onNodeClick?: (pagePath: string) => void;
}) {
  const strengthPercent = Math.round(connection.strength * 100);

  return (
    <div className="rounded-md border border-border bg-surface p-3 hover:bg-accent/5 transition-colors">
      <div className="flex items-start justify-between gap-2 mb-2">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <button
              className="text-sm font-medium hover:underline truncate"
              onClick={() => onNodeClick?.(connection.source_id)}
              title={connection.source_id}
            >
              {connection.source_label}
            </button>
            <span className="text-muted text-xs">↔</span>
            <button
              className="text-sm font-medium hover:underline truncate"
              onClick={() => onNodeClick?.(connection.target_id)}
              title={connection.target_id}
            >
              {connection.target_label}
            </button>
          </div>
          <div className="text-xs text-muted mt-1">{connection.reason}</div>
        </div>
        <div className="text-xs font-semibold text-accent whitespace-nowrap">
          {strengthPercent}%
        </div>
      </div>
      <div className="h-1 bg-muted rounded-full overflow-hidden">
        <div className="h-full bg-accent transition-all" style={{ width: `${strengthPercent}%` }} />
      </div>
    </div>
  );
}

function KnowledgeGapCard({
  gap,
  onNodeClick,
}: {
  gap: KnowledgeGap;
  onNodeClick?: (pagePath: string) => void;
}) {
  const severityColors = {
    high: 'border-destructive bg-destructive/10',
    medium: 'border-warning bg-warning/10',
    low: 'border-border bg-surface',
  };

  const severityLabels = {
    high: '高',
    medium: '中',
    low: '低',
  };

  const gapTypeLabels = {
    isolated_node: '孤立节点',
    sparse_community: '稀疏社区',
    bridge_node: '桥节点',
  };

  return (
    <div
      className={`rounded-md border p-3 ${severityColors[gap.severity as keyof typeof severityColors] ?? severityColors.low}`}
    >
      <div className="flex items-start justify-between gap-2 mb-2">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <span className="text-xs font-semibold px-2 py-0.5 rounded bg-muted">
              {gapTypeLabels[gap.gap_type as keyof typeof gapTypeLabels] ?? gap.gap_type}
            </span>
            <span className="text-xs text-muted">
              严重性: {severityLabels[gap.severity as keyof typeof severityLabels] ?? gap.severity}
            </span>
          </div>
          {gap.node_id.startsWith('community_') ? (
            <div className="text-sm font-medium">{gap.node_label}</div>
          ) : (
            <button
              className="text-sm font-medium hover:underline"
              onClick={() => onNodeClick?.(gap.node_id)}
              title={gap.node_id}
            >
              {gap.node_label}
            </button>
          )}
        </div>
      </div>
      <div className="text-xs text-muted mb-2">{gap.description}</div>
      <div className="text-xs text-accent italic">💡 {gap.suggestion}</div>
    </div>
  );
}
