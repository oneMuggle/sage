/**
 * 项目顾问卡片 (M3, 2026-10-12 / Phase P23 M3→M1 闭环增强)
 *
 * 在项目概览面板中显示 AI 顾问的健康评分、风险和建议。
 * 自动加载一次，支持手动刷新（30min 缓存由后端管理），
 * 支持点击改进建议一键唤起 M1 任务分解对话框并自动带入建议内容与原因。
 */

import { AlertTriangle, Lightbulb, PlusCircle, RefreshCw, Shield } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';

import { projectApi, type AdviceResult } from '../../shared/api';
import { Card, CardContent, CardHeader, CardTitle } from '../../shared/ui/Card';
import { Progress } from '../../shared/ui/Progress';

export interface ProjectAdvisorCardProps {
  projectId: string;
  /** M3→M1 联动：点击建议项的"分解为任务"按钮时触发，带入建议动作与原因 */
  onDecomposeTask?: (action?: string, reason?: string | null) => void;
}

/** 健康分数 → 颜色 */
function scoreColor(score: number): string {
  if (score >= 80) return 'text-green-500';
  if (score >= 60) return 'text-yellow-500';
  if (score >= 40) return 'text-orange-500';
  return 'text-red-500';
}

/** 健康分数 → 进度条颜色 */
function progressColor(score: number): string {
  if (score >= 80) return 'bg-green-500';
  if (score >= 60) return 'bg-yellow-500';
  if (score >= 40) return 'bg-orange-500';
  return 'bg-red-500';
}

/** 严重度 → badge 样式 */
function severityBadge(severity: string): string {
  switch (severity) {
    case 'high':
      return 'bg-red-500/20 text-red-400 border-red-500/30';
    case 'medium':
      return 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30';
    default:
      return 'bg-blue-500/20 text-blue-400 border-blue-500/30';
  }
}

/** 优先级 → badge 样式 */
function priorityBadge(priority: string): string {
  switch (priority) {
    case 'high':
      return 'bg-red-500/20 text-red-400';
    case 'medium':
      return 'bg-yellow-500/20 text-yellow-400';
    default:
      return 'bg-slate-500/20 text-slate-400';
  }
}

export function ProjectAdvisorCard({ projectId, onDecomposeTask }: ProjectAdvisorCardProps) {
  const [advice, setAdvice] = useState<AdviceResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);

  const fetchAdvice = useCallback(async () => {
    if (typeof projectApi?.getAdvice !== 'function') {
      setLoading(false);
      return;
    }
    try {
      setLoading(true);
      setError(null);
      const result = await projectApi.getAdvice(projectId);
      setAdvice(result ?? null);
    } catch (err) {
      setError(err instanceof Error ? err.message : '获取顾问建议失败');
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    void fetchAdvice();
  }, [fetchAdvice]);

  const handleRefresh = async () => {
    if (typeof projectApi?.refreshAdvice !== 'function') return;
    try {
      setRefreshing(true);
      setError(null);
      const result = await projectApi.refreshAdvice(projectId);
      setAdvice(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : '刷新失败');
    } finally {
      setRefreshing(false);
    }
  };

  if (loading) {
    return (
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center gap-2 text-sm">
            <Shield className="h-4 w-4" />
            AI 顾问
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="text-xs text-muted">分析中…</div>
        </CardContent>
      </Card>
    );
  }

  if (error) {
    return (
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center gap-2 text-sm">
            <Shield className="h-4 w-4" />
            AI 顾问
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="text-xs text-red-400">{error}</div>
        </CardContent>
      </Card>
    );
  }

  if (!advice) return null;

  const { healthScore, summary, risks, suggestions } = advice;
  const hasDetails = risks.length > 0 || suggestions.length > 0;

  return (
    <Card data-testid="project-advisor-card">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-2 text-sm">
            <Shield className="h-4 w-4" />
            AI 顾问
          </CardTitle>
          <button
            type="button"
            onClick={() => void handleRefresh()}
            disabled={refreshing}
            data-testid="advisor-refresh-btn"
            className="p-1 rounded hover:bg-bg-hover disabled:opacity-50"
            title="刷新分析"
            aria-label="刷新顾问分析"
          >
            <RefreshCw className={`h-3 w-3 ${refreshing ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </CardHeader>
      <CardContent>
        {/* 健康分数 */}
        <div className="flex items-center gap-3 mb-2">
          <div className="flex-1">
            <div className="flex items-center justify-between mb-1">
              <span className="text-xs text-muted">健康度</span>
              <span className={`text-sm font-semibold ${scoreColor(healthScore)}`}>
                {healthScore}
              </span>
            </div>
            <Progress value={healthScore} className={progressColor(healthScore)} />
          </div>
        </div>

        {/* 摘要 */}
        <p className="text-xs text-text/80 mb-2 leading-relaxed">{summary}</p>

        {/* 展开/收起 */}
        {hasDetails && (
          <button
            type="button"
            onClick={() => setExpanded(!expanded)}
            data-testid="advisor-toggle-details-btn"
            className="text-xs text-blue-400 hover:text-blue-300 mb-2"
          >
            {expanded
              ? '收起详情 ▴'
              : `展开详情 ▾ (${risks.length} 风险, ${suggestions.length} 建议)`}
          </button>
        )}

        {/* 详情 */}
        {expanded && (
          <div className="space-y-2 mt-2 pt-2 border-t border-border/50">
            {/* 风险 */}
            {risks.length > 0 && (
              <div>
                <div className="flex items-center gap-1 mb-1">
                  <AlertTriangle className="h-3 w-3 text-orange-400" />
                  <span className="text-xs font-medium text-orange-400">风险</span>
                </div>
                <ul className="space-y-1">
                  {risks.map((risk, idx) => (
                    <li key={idx} className="text-xs">
                      <span
                        className={`inline-block px-1 py-0.5 rounded text-ui-2xs border mr-1 ${severityBadge(risk.severity)}`}
                      >
                        {risk.severity}
                      </span>
                      <span>{risk.description}</span>
                      {risk.suggestion && (
                        <div className="text-ui-2xs text-muted ml-6 mt-0.5">
                          → {risk.suggestion}
                        </div>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {/* 建议 */}
            {suggestions.length > 0 && (
              <div>
                <div className="flex items-center gap-1 mb-1">
                  <Lightbulb className="h-3 w-3 text-yellow-400" />
                  <span className="text-xs font-medium text-yellow-400">改进建议</span>
                </div>
                <ul className="space-y-1">
                  {suggestions.map((sug, idx) => (
                    <li key={idx} className="text-xs flex flex-wrap items-start gap-1">
                      <span
                        className={`inline-block px-1 py-0.5 rounded text-ui-2xs shrink-0 ${priorityBadge(sug.priority)}`}
                      >
                        {sug.priority}
                      </span>
                      <span className="flex-1">{sug.action}</span>
                      {onDecomposeTask && (
                        <button
                          type="button"
                          onClick={() => onDecomposeTask(sug.action, sug.reason)}
                          data-testid={`advisor-decompose-suggestion-${idx}`}
                          className="shrink-0 inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded border border-border/60 hover:bg-bg-hover text-ui-2xs text-muted hover:text-blue-400"
                          title="将此建议分解为任务"
                          aria-label="分解为任务"
                        >
                          <PlusCircle className="h-3 w-3" />
                          <span>分解为任务</span>
                        </button>
                      )}
                      {sug.reason && (
                        <div className="text-ui-2xs text-muted ml-6 mt-0.5 w-full">
                          原因: {sug.reason}
                        </div>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}

        {/* 缓存时间 */}
        {advice.cachedAt && (
          <div className="text-ui-2xs text-muted mt-2">
            更新于 {new Date(advice.cachedAt * 1000).toLocaleTimeString()}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
