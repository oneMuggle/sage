/**
 * ``ResearchSummaryCard`` — scout_deep 调研报告展示组件（2026-10-28）。
 *
 * 展示 ``ResearchReport``：findings + sources + confidence，用户审阅后
 * 决定是否基于调研生成 plan。
 *
 * 交互：
 * - [基于调研生成 Plan] → 调用 onGeneratePlan()，planner 读取 research context
 * - [补充调研] → 调用 onResearchMore()（Phase 3 实现，当前 disabled）
 * - [放弃] → 调用 onDismiss()，清空 store 中的 researchReport
 */
import { BookOpen, ExternalLink, ChevronDown, ChevronUp } from 'lucide-react';
import { useState } from 'react';

import type {
  ResearchFinding,
  ResearchReport,
  ResearchSource,
} from '../shared/api/types/planModeTypes';

export type { ResearchFinding, ResearchReport, ResearchSource };

// ============================================================================
// Types
// ============================================================================

export interface ResearchSummaryCardProps {
  report: ResearchReport;
  onGeneratePlan: () => void;
  onResearchMore?: () => void;
  onDismiss: () => void;
}

// ============================================================================
// URL safety (2026-10-28 code review #17)
// ============================================================================

/**
 * 只允许 http/https URL，拒绝 javascript:/data:/vbscript: 等危险协议。
 * 来源为 web_search 结果，URL 未受信，必须白名单过滤后放入 href。
 */
function isSafeHttpUrl(url: string | undefined | null): string | undefined {
  if (!url) return undefined;
  try {
    const parsed = new URL(url);
    return parsed.protocol === 'http:' || parsed.protocol === 'https:' ? url : undefined;
  } catch {
    return undefined;
  }
}

// ============================================================================
// Component
// ============================================================================

export function ResearchSummaryCard({
  report,
  onGeneratePlan,
  onResearchMore,
  onDismiss,
}: ResearchSummaryCardProps) {
  const [sourcesExpanded, setSourcesExpanded] = useState(false);
  const [synthesisExpanded, setSynthesisExpanded] = useState(false);

  const confidencePercent = Math.round(report.confidence * 100);
  const confidenceColor =
    confidencePercent >= 70
      ? 'bg-green-500'
      : confidencePercent >= 40
        ? 'bg-yellow-500'
        : 'bg-red-500';

  const relevanceIcon = (relevance: string) => {
    switch (relevance) {
      case 'high':
        return '🔴';
      case 'medium':
        return '🟡';
      case 'low':
        return '🟢';
      default:
        return '⚪';
    }
  };

  return (
    <div className="border rounded-lg p-4 bg-bg-card space-y-4" data-testid="research-summary-card">
      {/* Header */}
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2">
          <BookOpen className="w-5 h-5 text-blue-500" />
          <h3 className="text-lg font-semibold">调研报告: {report.topic}</h3>
        </div>
        <div className="flex items-center gap-2 text-sm text-text-muted">
          <span>充分度:</span>
          <div className="w-24 h-2 bg-bg-hover rounded-full overflow-hidden">
            <div
              className={`h-full ${confidenceColor} transition-all`}
              style={{ width: `${confidencePercent}%` }}
              data-testid="confidence-bar"
            />
          </div>
          <span>{confidencePercent}%</span>
        </div>
      </div>

      {/* Meta */}
      <div className="flex gap-4 text-sm text-text-muted">
        <span>预估工作量: {report.estimated_effort}</span>
        <span>发现: {report.findings.length} 条</span>
        <span>来源: {report.sources.length} 个</span>
      </div>

      {/* Findings */}
      {report.findings.length > 0 && (
        <div className="space-y-2">
          <h4 className="font-medium text-sm">关键发现</h4>
          <ul className="space-y-2">
            {report.findings.map((finding, idx) => (
              <li key={idx} className="text-sm">
                <div className="flex items-start gap-2">
                  <span className="text-base">{relevanceIcon(finding.relevance)}</span>
                  <div className="flex-1">
                    <div className="font-medium">{finding.title}</div>
                    <div className="text-text-muted mt-0.5">{finding.summary}</div>
                    {finding.sources.length > 0 && (
                      <div className="text-xs text-text-muted mt-1">
                        来源: {finding.sources.slice(0, 2).join(', ')}
                        {finding.sources.length > 2 && ` +${finding.sources.length - 2}`}
                      </div>
                    )}
                  </div>
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Synthesis (collapsible) */}
      {report.synthesis && (
        <div>
          <button
            type="button"
            onClick={() => setSynthesisExpanded(!synthesisExpanded)}
            className="flex items-center gap-1 text-sm font-medium hover:text-blue-500 transition-colors"
            data-testid="synthesis-toggle"
          >
            {synthesisExpanded ? (
              <ChevronUp className="w-4 h-4" />
            ) : (
              <ChevronDown className="w-4 h-4" />
            )}
            综合报告 ({synthesisExpanded ? '收起' : '展开'})
          </button>
          {synthesisExpanded && (
            <div
              className="mt-2 p-3 bg-bg-hover rounded text-sm whitespace-pre-wrap max-h-96 overflow-y-auto"
              data-testid="synthesis-content"
            >
              {report.synthesis}
            </div>
          )}
        </div>
      )}

      {/* Sources (collapsible) */}
      {report.sources.length > 0 && (
        <div>
          <button
            type="button"
            onClick={() => setSourcesExpanded(!sourcesExpanded)}
            className="flex items-center gap-1 text-sm font-medium hover:text-blue-500 transition-colors"
            data-testid="sources-toggle"
          >
            {sourcesExpanded ? (
              <ChevronUp className="w-4 h-4" />
            ) : (
              <ChevronDown className="w-4 h-4" />
            )}
            参考来源 ({report.sources.length} 个)
          </button>
          {sourcesExpanded && (
            <ul className="mt-2 space-y-2">
              {report.sources.map((source, idx) => {
                const safeHref = isSafeHttpUrl(source.url);
                return (
                <li key={idx} className="text-sm border-l-2 border-blue-500 pl-3">
                  <a
                    href={safeHref ?? '#'}
                    target="_blank"
                    rel="noopener noreferrer"
                    className={`font-medium flex items-center gap-1 ${safeHref ? 'hover:text-blue-500' : 'pointer-events-none opacity-50'}`}
                    onClick={safeHref ? undefined : (e) => e.preventDefault()}
                  >
                    {source.title || source.url || '(no URL)'}
                    {safeHref && <ExternalLink className="w-3 h-3" />}
                  </a>
                  {source.snippet && (
                    <div className="text-text-muted mt-0.5 line-clamp-2">{source.snippet}</div>
                  )}
                </li>
                );
              })}
            </ul>
          )}
        </div>
      )}

      {/* Actions */}
      <div className="flex gap-2 pt-2 border-t">
        <button
          type="button"
          onClick={onGeneratePlan}
          className="px-4 py-2 bg-blue-500 text-white rounded hover:bg-blue-600 transition-colors font-medium"
          data-testid="research-generate-plan"
        >
          基于调研生成 Plan
        </button>
        <button
          type="button"
          onClick={onResearchMore}
          disabled={!onResearchMore}
          className="px-4 py-2 bg-bg-hover text-text-secondary rounded hover:bg-bg-active transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          data-testid="research-more"
          title={onResearchMore ? '补充调研（Phase 3）' : '补充调研功能开发中'}
        >
          补充调研
        </button>
        <button
          type="button"
          onClick={onDismiss}
          className="px-4 py-2 text-text-muted hover:text-text-primary transition-colors"
          data-testid="research-dismiss"
        >
          放弃
        </button>
      </div>
    </div>
  );
}
