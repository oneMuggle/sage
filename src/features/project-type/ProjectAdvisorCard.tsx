/**
 * 项目顾问卡片 (M3, 2026-10-12 / Phase P23 M3→M1 闭环增强 / Phase P30 M3 风险一键固化为 AI 防护约束)
 *
 * 在项目概览面板中显示 AI 顾问的健康评分、风险和建议。
 * 自动加载一次，支持手动刷新（30min 缓存由后端管理），
 * 支持点击改进建议一键唤起 M1 任务分解对话框，或点击风险项一键固化为 AI 行为约束规则。
 */

import { AlertTriangle, Check, Copy, Lightbulb, PlusCircle, RefreshCw, Shield } from 'lucide-react';
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
  const [copiedReport, setCopiedReport] = useState(false);
  const [guardingIdx, setGuardingIdx] = useState<number | null>(null);
  const [guardedRisks, setGuardedRisks] = useState<Set<number>>(new Set());
  const [guardedSuggestions, setGuardedSuggestions] = useState<Set<number>>(new Set());
  const [highRiskOnly, setHighRiskOnly] = useState(false);
  const [savedL4Report, setSavedL4Report] = useState(false);
  const [milestoneSuggestionIndices, setMilestoneSuggestionIndices] = useState<Set<number>>(new Set());

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

  const handleCreateRiskConstraint = async (
    risk: { severity: string; description: string; suggestion?: string | null },
    idx: number,
  ) => {
    if (guardingIdx === idx || guardedRisks.has(idx) || typeof projectApi?.createConstraint !== 'function') {
      return;
    }
    setGuardingIdx(idx);
    try {
      await projectApi.createConstraint(projectId, {
        category: 'risk_guard',
        content: risk.suggestion
          ? `${risk.description} — 防护规范：${risk.suggestion}`
          : risk.description,
        priority: risk.severity === 'high' ? 9 : 7,
      });
      setGuardedRisks((prev) => new Set(prev).add(idx));
    } catch {
      // ignore in test/offline mode
    } finally {
      setGuardingIdx(null);
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

  const handleCopyAdvisorMarkdown = () => {
    const lines = [
      `# AI 项目健康顾问诊断报告 (健康度: ${healthScore}/100)`,
      '',
      `> ${summary}`,
    ];
    if (risks.length > 0) {
      lines.push('', '## 风险项');
      risks.forEach((r) => {
        lines.push(`- **[${r.severity}]** ${r.description}${r.suggestion ? ` → 建议: ${r.suggestion}` : ''}`);
      });
    }
    if (suggestions.length > 0) {
      lines.push('', '## 改进建议');
      suggestions.forEach((s) => {
        lines.push(`- **[${s.priority}]** ${s.action}${s.reason ? ` (${s.reason})` : ''}`);
      });
    }
    try {
      void navigator.clipboard?.writeText(lines.join('\n'));
      setCopiedReport(true);
      setTimeout(() => setCopiedReport(false), 1800);
    } catch {
      // ignore clipboard errors in test/offline mode
    }
  };

  return (
    <Card data-testid="project-advisor-card">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-2 text-sm">
            <Shield className="h-4 w-4" />
            AI 顾问
          </CardTitle>
          <div className="flex items-center gap-1">
            <button
              type="button"
              data-testid="advisor-save-l4-btn"
              onClick={async () => {
                if (savedL4Report) return;
                setSavedL4Report(true);
                if (typeof projectApi?.addMaterial === 'function') {
                  try {
                    await projectApi.addMaterial(projectId, {
                      content: `# AI 顾问健康诊断报告 (${healthScore}/100)\n\n${summary}\n\n风险数: ${risks.length} · 建议数: ${suggestions.length}`,
                    });
                  } catch {
                    // ignore in test/offline mode
                  }
                }
              }}
              className="inline-flex items-center gap-1 rounded border border-border bg-background px-1.5 py-0.5 text-ui-2xs text-muted hover:bg-bg-hover hover:text-text"
            >
              {savedL4Report ? '已存 L4' : '存为 L4 资料'}
            </button>
            <button
              type="button"
              onClick={handleCopyAdvisorMarkdown}
              data-testid="advisor-copy-md-btn"
              className="inline-flex items-center gap-1 rounded border border-border bg-background px-1.5 py-0.5 text-ui-2xs text-muted hover:bg-bg-hover hover:text-text"
              title="复制 AI 顾问诊断报告 Markdown"
            >
              {copiedReport ? <Check className="h-3 w-3 text-green-500" /> : <Copy className="h-3 w-3" />}
              {copiedReport ? '已复制' : '复制诊断'}
            </button>
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
                <div className="flex flex-wrap items-center justify-between gap-1 mb-1">
                  <div className="flex items-center gap-1">
                    <AlertTriangle className="h-3 w-3 text-orange-400" />
                    <span className="text-xs font-medium text-orange-400">风险</span>
                  </div>
                  <div className="flex items-center gap-1">
                    <button
                      type="button"
                      data-testid="advisor-risk-filter-all"
                      onClick={() => setHighRiskOnly(false)}
                      className={`rounded border px-1.5 py-0.5 text-ui-2xs ${
                        !highRiskOnly ? 'border-primary bg-primary/10 text-primary' : 'border-border/60 text-muted'
                      }`}
                    >
                      全部
                    </button>
                    <button
                      type="button"
                      data-testid="advisor-risk-filter-high"
                      onClick={() => setHighRiskOnly(true)}
                      className={`rounded border px-1.5 py-0.5 text-ui-2xs ${
                        highRiskOnly ? 'border-primary bg-primary/10 text-primary' : 'border-border/60 text-muted'
                      }`}
                    >
                      仅高危
                    </button>
                    <button
                      type="button"
                      data-testid="advisor-guard-all-risks-btn"
                      onClick={async () => {
                        for (let i = 0; i < risks.length; i += 1) {
                          if (!guardedRisks.has(i)) {
                            await handleCreateRiskConstraint(risks[i], i);
                          }
                        }
                      }}
                      className="rounded border border-border/60 px-1.5 py-0.5 text-ui-2xs text-muted hover:text-emerald-500"
                    >
                      全部风险转约束
                    </button>
                  </div>
                </div>
                <ul className="space-y-1">
                  {risks.map((risk, idx) => {
                    if (highRiskOnly && risk.severity !== 'high') return null;
                    const isGuarded = guardedRisks.has(idx);
                    return (
                      <li key={idx} className="text-xs flex flex-wrap items-start gap-1">
                        <span
                          className={`inline-block px-1 py-0.5 rounded text-ui-2xs border shrink-0 ${severityBadge(risk.severity)}`}
                        >
                          {risk.severity}
                        </span>
                        <span className="flex-1">{risk.description}</span>
                        <button
                          type="button"
                          disabled={isGuarded || guardingIdx === idx}
                          onClick={() => void handleCreateRiskConstraint(risk, idx)}
                          data-testid={`advisor-risk-to-constraint-${idx}`}
                          className="shrink-0 inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded border border-border/60 hover:bg-bg-hover text-ui-2xs text-muted hover:text-emerald-500 disabled:opacity-60"
                          title="将此风险转化为项目 AI 防护约束"
                        >
                          {isGuarded ? (
                            <>
                              <Check className="h-3 w-3 text-emerald-500" />
                              <span>已固化约束</span>
                            </>
                          ) : (
                            <>
                              <Shield className="h-3 w-3" />
                              <span>固化为约束</span>
                            </>
                          )}
                        </button>
                        {risk.suggestion && (
                          <div className="text-ui-2xs text-muted ml-6 mt-0.5 w-full">
                            → {risk.suggestion}
                          </div>
                        )}
                      </li>
                    );
                  })}
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
                      <button
                        type="button"
                        disabled={guardedSuggestions.has(idx)}
                        onClick={async () => {
                          if (
                            guardedSuggestions.has(idx) ||
                            typeof projectApi?.createConstraint !== 'function'
                          ) {
                            return;
                          }
                          try {
                            await projectApi.createConstraint(projectId, {
                              category: 'convention',
                              content: sug.reason ? `${sug.action}（${sug.reason}）` : sug.action,
                              priority: sug.priority === 'high' ? 8 : 6,
                            });
                            setGuardedSuggestions((prev) => new Set(prev).add(idx));
                          } catch {
                            // ignore in test/offline mode
                          }
                        }}
                        data-testid={`advisor-suggestion-to-constraint-${idx}`}
                        className="shrink-0 inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded border border-border/60 hover:bg-bg-hover text-ui-2xs text-muted hover:text-emerald-500 disabled:opacity-60"
                        title="将此改进建议固化为 L2 行为约束"
                      >
                        <Shield className="h-3 w-3" />
                        <span>{guardedSuggestions.has(idx) ? '已固化约束' : '固化为约束'}</span>
                      </button>
                      <button
                        type="button"
                        data-testid={`advisor-suggestion-to-milestone-${idx}`}
                        onClick={async () => {
                          if (milestoneSuggestionIndices.has(idx)) return;
                          setMilestoneSuggestionIndices((prev) => new Set(prev).add(idx));
                          if (typeof projectApi?.createMilestone === 'function') {
                            try {
                              await projectApi.createMilestone(projectId, {
                                title: sug.action.slice(0, 60),
                                description: sug.reason || '来源于 AI 顾问改进建议',
                                sortOrder: idx + 1,
                              });
                            } catch {
                              // ignore in test/offline mode
                            }
                          }
                        }}
                        className="shrink-0 inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded border border-border/60 hover:bg-bg-hover text-ui-2xs text-muted hover:text-primary"
                      >
                        <span>{milestoneSuggestionIndices.has(idx) ? '已转里程碑' : '+里程碑'}</span>
                      </button>
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
