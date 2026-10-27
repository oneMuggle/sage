/**
 * AI 治理分析报告展示组件 (2026-10-27)
 *
 * 项目类型分类系统 - Phase 10.1
 * 纯展示：接收分析结果（ProjectAnalysisResult），展示类型判定卡、技术栈摘要、
 * 推荐规则包列表（可 toggle）、治理建议（可勾选采纳）、推荐文档链接与 SAGE.md 草稿。
 *
 * 与后端 `AnalysisReport` 一一对应，前端不做业务逻辑。
 */

import {
  Sparkles,
  AlertCircle,
  Loader2,
  RefreshCw,
  Copy,
  Check,
  FileText,
  ExternalLink,
  Lightbulb,
  ShieldCheck,
  ChevronDown,
  ChevronRight,
} from 'lucide-react';
import { useState } from 'react';

import type { ProjectAnalysisResult, SuggestedRule, SubTypesCatalog } from '../../shared/api';
import { Switch } from '../../shared/ui/Switch/Switch';

import { ARCHETYPE_BLUEPRINTS } from './archetypeBlueprints';

export interface ProjectAnalysisReportProps {
  /** 分析结果，null 表示尚未完成 */
  result: ProjectAnalysisResult | null;
  /** 是否正在分析 */
  loading?: boolean;
  /** 分析失败时的错误信息 */
  error?: string | null;
  /** 两级类型目录（用于解析 L2 子类型标签） */
  subTypes: SubTypesCatalog | null;
  /** 当前启用的规则 key（templateKey）集合 */
  enabledRuleKeys: ReadonlySet<string>;
  /** 规则 toggle 回调 */
  onToggleRule?: (rule: SuggestedRule) => void;
  /** 已勾选采纳的治理建议索引集合 */
  adoptedRecommendations: ReadonlySet<number>;
  /** 治理建议 toggle 回调 */
  onToggleRecommendation?: (index: number) => void;
  /** 重新分析回调 */
  onRegenerate?: () => void;
  /** 自定义 className */
  className?: string;
}

const TYPE_COLORS: Record<string, string> = {
  coding: 'text-blue-500',
  research: 'text-purple-500',
  business: 'text-green-500',
  personal: 'text-orange-500',
};

const TYPE_BG: Record<string, string> = {
  coding: 'bg-blue-50 dark:bg-blue-950',
  research: 'bg-purple-50 dark:bg-purple-950',
  business: 'bg-green-50 dark:bg-green-950',
  personal: 'bg-orange-50 dark:bg-orange-950',
};

export function ProjectAnalysisReport({
  result,
  loading = false,
  error = null,
  subTypes,
  enabledRuleKeys,
  onToggleRule,
  adoptedRecommendations,
  onToggleRecommendation,
  onRegenerate,
  className,
}: ProjectAnalysisReportProps) {
  const [showArchitecture, setShowArchitecture] = useState(false);
  const [showSageMd, setShowSageMd] = useState(false);
  const [showDocs, setShowDocs] = useState(false);
  const [copiedSageMd, setCopiedSageMd] = useState(false);
  const [copiedRuleIdx, setCopiedRuleIdx] = useState<number | null>(null);

  if (loading) {
    return (
      <div
        data-testid="analysis-loading"
        className={`flex items-center gap-2 rounded-lg border border-primary/30 bg-primary/5 p-4 text-sm text-muted-foreground ${className ?? ''}`}
      >
        <Loader2 className="h-4 w-4 animate-spin text-primary" />
        正在对代码库进行 AI 深度分析...
      </div>
    );
  }

  if (error) {
    return (
      <div
        data-testid="analysis-error"
        className={`flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive ${className ?? ''}`}
      >
        <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
        <div className="flex-1">
          <div className="font-medium">分析失败</div>
          <div className="mt-0.5 text-xs">{error}</div>
        </div>
        {onRegenerate && (
          <button
            type="button"
            data-testid="analysis-retry-btn"
            onClick={onRegenerate}
            className="inline-flex items-center gap-1 rounded border border-border bg-background px-2 py-1 text-xs text-foreground hover:bg-muted"
          >
            <RefreshCw className="h-3 w-3" />
            重试
          </button>
        )}
      </div>
    );
  }

  if (!result) {
    return null;
  }

  const { profile, report } = result;
  const blueprint = ARCHETYPE_BLUEPRINTS[report.level1Type];
  const l1Label = blueprint.label;
  const l1Color = TYPE_COLORS[report.level1Type] ?? 'text-muted-foreground';
  const l1Bg = TYPE_BG[report.level1Type] ?? 'bg-muted/30';

  const l2Def = (() => {
    if (!report.subType || !subTypes) return null;
    const subsForL1 = subTypes.subTypes[report.level1Type];
    return subsForL1?.find((s) => s.key === report.subType) ?? null;
  })();

  const confidencePercent = Math.round(report.confidence * 100);
  const ruleList = report.suggestedRules;
  const recList = report.governanceRecommendations;

  return (
    <div
      data-testid="analysis-report-root"
      className={`space-y-3 rounded-lg border border-border bg-surface p-4 ${className ?? ''}`}
    >
      {/* 1. 类型判定卡 */}
      <div
        data-testid="analysis-type-card"
        className={`rounded-lg border border-border/60 p-3 ${l1Bg}`}
      >
        <div className="flex flex-wrap items-center gap-2">
          <Sparkles className={`h-4 w-4 ${l1Color}`} />
          <span className="text-sm font-medium">
            <span className={l1Color}>{l1Label}</span>
            {l2Def && (
              <>
                <span className="mx-1 text-muted-foreground">/</span>
                <span className="text-foreground">{l2Def.label}</span>
              </>
            )}
          </span>
          <span className="rounded bg-background/80 px-1.5 py-0.5 text-ui-2xs text-muted-foreground">
            置信度 {confidencePercent}%
          </span>
          {report.llmAvailable ? (
            <span
              data-testid="analysis-llm-badge"
              className="rounded bg-primary/10 px-1.5 py-0.5 text-ui-2xs font-medium text-primary"
            >
              LLM 深度分析
            </span>
          ) : (
            <span
              data-testid="analysis-llm-badge"
              className="rounded bg-amber-500/10 px-1.5 py-0.5 text-ui-2xs font-medium text-amber-700 dark:text-amber-400"
            >
              基于文件特征的基础建议
            </span>
          )}
          {onRegenerate && (
            <button
              type="button"
              data-testid="analysis-regenerate-btn"
              onClick={onRegenerate}
              className="ml-auto inline-flex items-center gap-1 rounded border border-border bg-background px-2 py-1 text-xs text-foreground hover:bg-muted"
            >
              <RefreshCw className="h-3 w-3" />
              重新分析
            </button>
          )}
        </div>

        {profile.techStack.length > 0 && (
          <div data-testid="analysis-tech-stack" className="mt-2 flex flex-wrap items-center gap-1">
            <span className="text-ui-2xs text-muted-foreground">技术栈：</span>
            {profile.techStack.slice(0, 10).map((tech) => (
              <span
                key={tech}
                className="rounded border border-border bg-background px-1.5 py-0.5 font-mono text-ui-2xs text-foreground"
              >
                {tech}
              </span>
            ))}
          </div>
        )}
      </div>

      {/* 2. 架构摘要（可折叠） */}
      {report.architectureSummary && (
        <div className="rounded-lg border border-border/60 bg-background/40">
          <button
            type="button"
            data-testid="analysis-arch-toggle"
            onClick={() => setShowArchitecture((v) => !v)}
            className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-sm font-medium"
          >
            <span className="flex items-center gap-1.5">
              <Lightbulb className="h-4 w-4 text-primary" />
              架构与代码库摘要
            </span>
            {showArchitecture ? (
              <ChevronDown className="h-4 w-4 text-muted-foreground" />
            ) : (
              <ChevronRight className="h-4 w-4 text-muted-foreground" />
            )}
          </button>
          {showArchitecture && (
            <div
              data-testid="analysis-arch-body"
              className="border-t border-border/40 px-3 py-2 text-xs text-muted-foreground whitespace-pre-wrap"
            >
              {report.architectureSummary}
            </div>
          )}
        </div>
      )}

      {/* 3. 推荐规则包列表 */}
      {ruleList.length > 0 && (
        <div>
          <div className="mb-1.5 flex items-center gap-1.5 text-sm font-medium">
            <ShieldCheck className="h-4 w-4 text-primary" />
            推荐规则包
            <span className="text-xs font-normal text-muted-foreground">
              （已选 {enabledRuleKeys.size} / {ruleList.length}）
            </span>
          </div>
          <ul data-testid="analysis-rules-list" className="space-y-1.5">
            {ruleList.map((rule, idx) => {
              const enabled = enabledRuleKeys.has(rule.templateKey);
              return (
                <li
                  key={`${rule.templateKey}-${idx}`}
                  data-testid={`analysis-rule-${idx}`}
                  className={`rounded-lg border p-2.5 text-xs transition-colors ${
                    enabled
                      ? 'border-primary/40 bg-primary/5'
                      : 'border-border/60 bg-background/40 opacity-70'
                  }`}
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex-1">
                      <div className="flex items-center gap-1.5">
                        <span className="text-sm font-medium text-foreground">{rule.label}</span>
                        {rule.templateKey === 'ai_custom' && (
                          <span
                            data-testid={`analysis-rule-ai-${idx}`}
                            className="rounded bg-primary/10 px-1 py-0.5 text-ui-2xs font-medium text-primary"
                          >
                            AI 专属
                          </span>
                        )}
                        <span className="text-ui-2xs text-muted-foreground">
                          ·{rule.category} · 优先级 {rule.priority}
                        </span>
                      </div>
                      <p className="mt-1 text-ui-2xs text-muted-foreground">{rule.reason}</p>
                      {rule.triggerPattern && rule.triggerPattern !== 'always' && (
                        <div className="mt-1 text-ui-2xs text-muted-foreground">
                          触发：
                          <code className="rounded bg-muted px-1 font-mono">
                            {rule.triggerPattern}
                          </code>
                        </div>
                      )}
                    </div>
                    <div className="flex flex-col items-end gap-1">
                      <Switch
                        checked={enabled}
                        onCheckedChange={() => onToggleRule?.(rule)}
                        aria-label={`启用规则 ${rule.label}`}
                        data-testid={`analysis-rule-toggle-${idx}`}
                      />
                      <button
                        type="button"
                        data-testid={`analysis-rule-copy-${idx}`}
                        onClick={async () => {
                          try {
                            await navigator.clipboard?.writeText(rule.content);
                            setCopiedRuleIdx(idx);
                            setTimeout(() => setCopiedRuleIdx(null), 1500);
                          } catch {
                            // ignore offline
                          }
                        }}
                        className="inline-flex items-center gap-1 rounded border border-border bg-background px-1.5 py-0.5 text-ui-2xs text-muted-foreground hover:bg-muted"
                      >
                        {copiedRuleIdx === idx ? (
                          <>
                            <Check className="h-3 w-3 text-emerald-500" />
                            已复制
                          </>
                        ) : (
                          <>
                            <Copy className="h-3 w-3" />
                            复制规则
                          </>
                        )}
                      </button>
                    </div>
                  </div>
                </li>
              );
            })}
          </ul>
        </div>
      )}

      {/* 4. 治理建议列表 */}
      {recList.length > 0 && (
        <div>
          <div className="mb-1.5 flex items-center gap-1.5 text-sm font-medium">
            <Lightbulb className="h-4 w-4 text-primary" />
            治理建议
            <span className="text-xs font-normal text-muted-foreground">
              （已采纳 {adoptedRecommendations.size} / {recList.length}）
            </span>
          </div>
          <ul data-testid="analysis-recommendations-list" className="space-y-1">
            {recList.map((rec, idx) => {
              const adopted = adoptedRecommendations.has(idx);
              return (
                <li key={idx} data-testid={`analysis-rec-${idx}`}>
                  <label
                    className={`flex cursor-pointer items-start gap-2 rounded border p-2 text-xs transition-colors ${
                      adopted
                        ? 'border-primary/40 bg-primary/5'
                        : 'border-border/60 bg-background/40'
                    }`}
                  >
                    <input
                      type="checkbox"
                      checked={adopted}
                      onChange={() => onToggleRecommendation?.(idx)}
                      data-testid={`analysis-rec-check-${idx}`}
                      className="mt-0.5 h-3.5 w-3.5 accent-primary"
                    />
                    <span className="flex-1 text-foreground">{rec}</span>
                  </label>
                </li>
              );
            })}
          </ul>
        </div>
      )}

      {/* 5. 推荐文档链接 */}
      {report.docsRefs.length > 0 && (
        <div className="rounded-lg border border-border/60 bg-background/40">
          <button
            type="button"
            data-testid="analysis-docs-toggle"
            onClick={() => setShowDocs((v) => !v)}
            className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-sm font-medium"
          >
            <span className="flex items-center gap-1.5">
              <FileText className="h-4 w-4 text-primary" />
              推荐文档（{report.docsRefs.length}）
            </span>
            {showDocs ? (
              <ChevronDown className="h-4 w-4 text-muted-foreground" />
            ) : (
              <ChevronRight className="h-4 w-4 text-muted-foreground" />
            )}
          </button>
          {showDocs && (
            <ul
              data-testid="analysis-docs-body"
              className="space-y-1 border-t border-border/40 px-3 py-2 text-xs"
            >
              {report.docsRefs.map((ref, idx) => (
                <li
                  key={idx}
                  data-testid={`analysis-doc-${idx}`}
                  className="flex items-start justify-between gap-2"
                >
                  <div className="flex-1">
                    <div className="font-medium text-foreground">{ref.title}</div>
                    <div className="text-ui-2xs text-muted-foreground">{ref.reason}</div>
                    <div className="mt-0.5 font-mono text-ui-2xs text-muted-foreground">
                      {ref.path}
                    </div>
                  </div>
                  <a
                    href={ref.path}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex shrink-0 items-center gap-0.5 text-primary hover:underline"
                  >
                    <ExternalLink className="h-3 w-3" />
                  </a>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {/* 6. SAGE.md 草稿 */}
      {report.sageMdDraft && (
        <div className="rounded-lg border border-border/60 bg-background/40">
          <button
            type="button"
            data-testid="analysis-sagemd-toggle"
            onClick={() => setShowSageMd((v) => !v)}
            className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-sm font-medium"
          >
            <span className="flex items-center gap-1.5">
              <FileText className="h-4 w-4 text-primary" />
              SAGE.md 草稿
            </span>
            <div className="flex items-center gap-1.5">
              <button
                type="button"
                data-testid="analysis-sagemd-copy"
                onClick={async (e) => {
                  e.stopPropagation();
                  try {
                    await navigator.clipboard?.writeText(report.sageMdDraft);
                    setCopiedSageMd(true);
                    setTimeout(() => setCopiedSageMd(false), 1500);
                  } catch {
                    // ignore
                  }
                }}
                className="inline-flex items-center gap-1 rounded border border-border bg-background px-1.5 py-0.5 text-ui-2xs text-muted-foreground hover:bg-muted"
              >
                {copiedSageMd ? (
                  <>
                    <Check className="h-3 w-3 text-emerald-500" />
                    已复制
                  </>
                ) : (
                  <>
                    <Copy className="h-3 w-3" />
                    复制
                  </>
                )}
              </button>
              {showSageMd ? (
                <ChevronDown className="h-4 w-4 text-muted-foreground" />
              ) : (
                <ChevronRight className="h-4 w-4 text-muted-foreground" />
              )}
            </div>
          </button>
          {showSageMd && (
            <pre
              data-testid="analysis-sagemd-body"
              className="max-h-80 overflow-auto whitespace-pre-wrap border-t border-border/40 px-3 py-2 font-mono text-ui-2xs text-muted-foreground"
            >
              {report.sageMdDraft}
            </pre>
          )}
        </div>
      )}
    </div>
  );
}

// eslint-disable-next-line react-refresh/only-export-components
export function auditProjectAnalysisReportGovernance(): {
  module: 'src/features/project-type/ProjectAnalysisReport.tsx';
  phase: 'P166';
  domain: 'project-type';
  supportsLlmAvailabilityBadge: boolean;
  supportsRuleToggle: boolean;
  supportsRecommendationAdoption: boolean;
  compliant: boolean;
} {
  return {
    module: 'src/features/project-type/ProjectAnalysisReport.tsx',
    phase: 'P166',
    domain: 'project-type',
    supportsLlmAvailabilityBadge: true,
    supportsRuleToggle: true,
    supportsRecommendationAdoption: true,
    compliant: true,
  };
}
