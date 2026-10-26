/**
 * RecallMetrics - 召回指标与 A/B 变体对比（P0-3）
 *
 * 后端 `adapter.py` 的召回路径早就在做 A/B 融合权重实验
 * （A = [0.2, 0.8] 嵌入器基线 / B = [0.5, 0.5] 均权对照，用 md5(query) 选路），
 * 但两个变体从未被分别度量过 —— 落库后这张表第一次能回答
 * 「哪个变体的反馈率更高」。
 *
 * 用户在这里对最近一次召回点 👍 / 👎，反馈回填 `memory_recall_log.user_feedback`，
 * 正反馈计数不再恒为 0。
 */
import React, { useCallback, useEffect, useState } from 'react';

import { invoke } from '../../shared/api/desktopInvoke';

export interface RecallVariantBucket {
  total: number;
  feedback_count: number;
  positive_count: number;
  negative_count: number;
  satisfaction_rate: number;
  feedback_satisfaction_rate: number;
  avg_result_count: number;
}

export interface RecallMetricsSummary {
  total_recalls: number;
  feedback_count: number;
  positive_count: number;
  negative_count: number;
  satisfaction_rate: number;
  feedback_satisfaction_rate: number;
  avg_result_count: number;
  by_variant: Record<string, RecallVariantBucket>;
}

export interface RecentRecallEvent {
  id: string;
  query_hash: string;
  session_id: string | null;
  variant: string | null;
  weights_json: string | null;
  result_count: number | null;
  user_feedback: string | null;
  created_at: number;
}

interface RecallMetricsResponse {
  metrics: RecallMetricsSummary;
  recent: RecentRecallEvent[];
}

/**
 * A/B 变体对比结论。
 *
 * 只有两边**都有反馈**时才给结论 —— 反馈量不足时任何"哪个更好"的判断都是
 * 噪音，宁可说"数据不足"。
 */
export interface VariantComparison {
  variantA: string | null;
  variantB: string | null;
  /** 反馈率更高的一侧；数据不足时为 null */
  leader: string | null;
  /** 领先方的反馈满意度优势（绝对值）；数据不足时为 null */
  margin: number | null;
  reason: string;
}

export function compareVariants(byVariant: Record<string, RecallVariantBucket>): VariantComparison {
  const names = Object.keys(byVariant).sort();
  const variantA = names[0] ?? null;
  const variantB = names[1] ?? null;

  if (!variantA || !variantB) {
    return {
      variantA,
      variantB,
      leader: null,
      margin: null,
      reason: '只有一个变体有数据，暂无对比',
    };
  }

  const a = byVariant[variantA];
  const b = byVariant[variantB];

  if (a.feedback_count < 5 || b.feedback_count < 5) {
    return {
      variantA,
      variantB,
      leader: null,
      margin: null,
      reason: `反馈量不足（${variantA}: ${a.feedback_count} / ${variantB}: ${b.feedback_count}，各需 ≥5）`,
    };
  }

  const rateA = a.feedback_satisfaction_rate;
  const rateB = b.feedback_satisfaction_rate;
  const margin = Number(Math.abs(rateA - rateB).toFixed(4));
  const leader = rateA === rateB ? null : rateA > rateB ? variantA : variantB;

  return {
    variantA,
    variantB,
    leader,
    margin,
    reason: leader
      ? `变体 ${leader} 的反馈满意度高出 ${(margin * 100).toFixed(1)} 个百分点`
      : '两个变体的反馈满意度持平',
  };
}

/** 找出某个变体最近一次用到的融合权重（从 recent 事件里反查）。 */
export function findVariantWeights(recent: RecentRecallEvent[], variant: string): string | null {
  const hit = recent.find((event) => event.variant === variant && event.weights_json);
  return hit?.weights_json ?? null;
}

const formatTime = (timestamp: number): string => {
  try {
    return new Date(timestamp * 1000).toLocaleString('zh-CN');
  } catch {
    return String(timestamp);
  }
};

const formatRate = (rate: number): string => `${(rate * 100).toFixed(1)}%`;

export const RecallMetrics: React.FC = () => {
  const [summary, setSummary] = useState<RecallMetricsSummary | null>(null);
  const [recent, setRecent] = useState<RecentRecallEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [pendingId, setPendingId] = useState<string | null>(null);

  const fetchMetrics = useCallback(async () => {
    setLoading(true);
    try {
      const result = await invoke<RecallMetricsResponse>('get_recall_metrics', { limit: 20 });
      setSummary(result.metrics);
      setRecent(result.recent ?? []);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchMetrics();
  }, [fetchMetrics]);

  const submitFeedback = async (logId: string, feedback: 'up' | 'down') => {
    setPendingId(logId);
    try {
      await invoke('submit_recall_feedback', { logId, feedback });
      await fetchMetrics();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setPendingId(null);
    }
  };

  const comparison = summary ? compareVariants(summary.by_variant) : null;

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-medium text-text">召回指标</h3>
        <button onClick={fetchMetrics} className="text-sm text-primary hover:text-primary-hover">
          刷新
        </button>
      </div>

      {error && (
        <p role="alert" className="text-xs text-error">
          {error}
        </p>
      )}

      {loading && !summary ? (
        <div className="text-muted text-sm">加载中...</div>
      ) : !summary ? (
        <div className="text-center py-6 text-muted text-sm">暂无召回指标</div>
      ) : (
        <>
          {/* 总体指标 */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-sm">
            <div className="bg-surface rounded-lg border border-border p-3">
              <div className="text-xs text-muted">总召回</div>
              <div className="text-lg text-text">{summary.total_recalls}</div>
            </div>
            <div className="bg-surface rounded-lg border border-border p-3">
              <div className="text-xs text-muted">反馈数</div>
              <div className="text-lg text-text">{summary.feedback_count}</div>
            </div>
            <div className="bg-surface rounded-lg border border-border p-3">
              <div className="text-xs text-muted">好评 / 差评</div>
              <div className="text-lg text-text">
                {summary.positive_count} / {summary.negative_count}
              </div>
            </div>
            <div className="bg-surface rounded-lg border border-border p-3">
              <div className="text-xs text-muted">平均结果数</div>
              <div className="text-lg text-text">{summary.avg_result_count.toFixed(1)}</div>
            </div>
          </div>

          <p className="text-xs text-muted">
            整体满意度 {formatRate(summary.satisfaction_rate)}
            （分母 = 全部召回）；反馈满意度 {formatRate(summary.feedback_satisfaction_rate)}
            （分母 = 有反馈的召回）。
          </p>

          {/* A/B 变体对比 —— 本轮改造的核心产出 */}
          <div>
            <h4 className="text-sm font-medium text-text-secondary mb-2">A/B 变体对比</h4>
            {Object.keys(summary.by_variant).length === 0 ? (
              <div className="text-center py-4 text-muted text-sm">暂无变体数据</div>
            ) : (
              <>
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-xs text-muted text-left">
                      <th className="py-1 pr-2">变体</th>
                      <th className="py-1 pr-2">权重</th>
                      <th className="py-1 pr-2">召回</th>
                      <th className="py-1 pr-2">反馈</th>
                      <th className="py-1 pr-2">反馈好评率</th>
                      <th className="py-1 pr-2">均结果数</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(summary.by_variant).map(([variant, bucket]) => (
                      <tr key={variant} className="border-t border-border">
                        <td className="py-1 pr-2 font-mono text-text">{variant}</td>
                        <td className="py-1 pr-2 text-text-secondary font-mono text-xs">
                          {findVariantWeights(recent, variant) ?? '—'}
                        </td>
                        <td className="py-1 pr-2 text-text">{bucket.total}</td>
                        <td className="py-1 pr-2 text-text">{bucket.feedback_count}</td>
                        <td className="py-1 pr-2 text-text">
                          {formatRate(bucket.feedback_satisfaction_rate)}
                        </td>
                        <td className="py-1 pr-2 text-text">
                          {bucket.avg_result_count.toFixed(1)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {comparison && (
                  <p className="mt-2 text-xs text-muted">
                    结论：{comparison.reason}
                    {comparison.leader && comparison.margin !== null && (
                      <>
                        （变体 {comparison.variantA} vs {comparison.variantB}）
                      </>
                    )}
                  </p>
                )}
              </>
            )}
          </div>

          {/* 最近召回 + 反馈入口 */}
          <div>
            <h4 className="text-sm font-medium text-text-secondary mb-2">最近召回</h4>
            {recent.length === 0 ? (
              <div className="text-center py-4 text-muted text-sm">暂无召回记录</div>
            ) : (
              <ul className="space-y-2">
                {recent.map((event) => (
                  <li
                    key={event.id}
                    className="bg-surface rounded-lg shadow-sm p-3 border border-border text-sm"
                  >
                    <div className="flex items-center justify-between gap-3">
                      <div className="min-w-0">
                        <div className="text-xs text-muted font-mono truncate">
                          {event.query_hash.slice(0, 12)}…
                          {event.variant ? ` · 变体 ${event.variant}` : ''}
                          {event.weights_json ? ` · ${event.weights_json}` : ''}
                        </div>
                        <div className="text-xs text-muted mt-1">
                          {formatTime(event.created_at)} · {event.result_count ?? 0} 条结果
                        </div>
                      </div>
                      <div className="flex items-center gap-2 shrink-0">
                        <button
                          onClick={() => submitFeedback(event.id, 'up')}
                          disabled={pendingId === event.id}
                          aria-label="召回有帮助"
                          className={`px-2 py-1 text-xs rounded border ${
                            event.user_feedback === 'up'
                              ? 'border-success text-success'
                              : 'border-border text-text-secondary hover:text-text'
                          }`}
                        >
                          👍
                        </button>
                        <button
                          onClick={() => submitFeedback(event.id, 'down')}
                          disabled={pendingId === event.id}
                          aria-label="召回没帮助"
                          className={`px-2 py-1 text-xs rounded border ${
                            event.user_feedback === 'down'
                              ? 'border-error text-error'
                              : 'border-border text-text-secondary hover:text-text'
                          }`}
                        >
                          👎
                        </button>
                      </div>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </>
      )}
    </div>
  );
};

export default RecallMetrics;
