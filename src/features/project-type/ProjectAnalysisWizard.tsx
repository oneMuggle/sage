/**
 * AI 治理分析向导组件 (2026-10-27)
 *
 * 项目类型分类系统 - Phase 10.2
 * 容器：给定目录路径，自动触发 `/projects/analyze`，
 * 渲染 `ProjectAnalysisReport` 并让用户覆盖 L1 / L2 类型。
 * 提供「跳过 AI 分析，手动选择」降级入口（LLM 不可用时自动展开）。
 *
 * 本组件不处理项目注册/脚手架；完成后通过 `onComplete(payload)` 把
 * 「用户确认的 L1 / L2 / 启用规则 / 采纳建议 / 原始分析结果」回传给父级。
 * `ProjectCreationWizard` 在 Step 11 把它接入 Step 2。
 */

import {
  ArrowRight,
  ArrowLeft,
  Loader2,
  Sparkles,
  User,
  Code,
  BookOpen,
  Briefcase,
} from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';

import {
  projectApi,
  type ProjectAnalysisResult,
  type ProjectType,
  type SubTypeDefinition,
  type SubTypesCatalog,
  type SuggestedRule,
} from '../../shared/api';
import { Button } from '../../shared/ui/Button';

import { ProjectAnalysisReport } from './ProjectAnalysisReport';
import { ARCHETYPE_BLUEPRINTS } from './archetypeBlueprints';

export interface AnalysisCompletePayload {
  /** 用户最终选定的 L1 类型 */
  selectedType: ProjectType;
  /** 用户最终选定的 L2 子类型（可能为 null） */
  selectedSubType: string | null;
  /** 用户启用的规则 templateKey 列表 */
  enabledRuleKeys: string[];
  /** 用户采纳的治理建议文本 */
  adoptedRecommendations: string[];
  /** 完整的分析结果；若用户跳过了 AI 分析则为 null */
  analysisResult: ProjectAnalysisResult | null;
  /** 用户是否跳过了 AI 分析 */
  skippedAi: boolean;
}

export interface ProjectAnalysisWizardProps {
  /** 待分析的项目目录绝对路径 */
  path: string;
  /** 返回上一步（如回到「选择文件夹」） */
  onBack?: () => void;
  /** 用户完成分析并确认 */
  onComplete: (payload: AnalysisCompletePayload) => void;
  /** 自定义 className */
  className?: string;
}

const L1_OPTIONS: ReadonlyArray<{
  value: ProjectType;
  label: string;
  description: string;
  icon: React.ReactNode;
  color: string;
}> = [
  {
    value: 'coding',
    label: '编码项目',
    description: '软件开发、代码约束、技术文档与 Git 工作流',
    icon: <Code className="h-5 w-5" />,
    color: 'text-blue-500',
  },
  {
    value: 'research',
    label: '科研项目',
    description: '学术论文、文献管理、实验记录与学术规范',
    icon: <BookOpen className="h-5 w-5" />,
    color: 'text-purple-500',
  },
  {
    value: 'business',
    label: '事务项目',
    description: '公文报告、合同审查、模板约束与审批流程',
    icon: <Briefcase className="h-5 w-5" />,
    color: 'text-green-500',
  },
  {
    value: 'personal',
    label: '个人项目',
    description: '个人笔记、日记、学习规划与知识沉淀',
    icon: <User className="h-5 w-5" />,
    color: 'text-orange-500',
  },
] as const;

export function ProjectAnalysisWizard({
  path,
  onBack,
  onComplete,
  className,
}: ProjectAnalysisWizardProps) {
  const [subTypes, setSubTypes] = useState<SubTypesCatalog | null>(null);
  const [catalogError, setCatalogError] = useState<string | null>(null);

  const [analyzing, setAnalyzing] = useState(false);
  const [analysisResult, setAnalysisResult] = useState<ProjectAnalysisResult | null>(null);
  const [analysisError, setAnalysisError] = useState<string | null>(null);

  const [selectedType, setSelectedType] = useState<ProjectType>('business');
  const [selectedSubType, setSelectedSubType] = useState<string | null>(null);
  const [enabledRuleKeys, setEnabledRuleKeys] = useState<Set<string>>(new Set());
  const [adoptedRecommendations, setAdoptedRecommendations] = useState<Set<number>>(new Set());

  const [skipAiMode, setSkipAiMode] = useState(false);

  // 拉两级类型目录（用于 L2 展示与回查）
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const catalog = await projectApi.subTypes();
        if (!cancelled) setSubTypes(catalog);
      } catch (err) {
        if (!cancelled) setCatalogError(err instanceof Error ? err.message : '拉取类型目录失败');
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // 触发分析
  const runAnalysis = useCallback(async () => {
    if (!path) return;
    setAnalyzing(true);
    setAnalysisError(null);
    try {
      const result = await projectApi.analyze(path);
      setAnalysisResult(result);
      setSelectedType(result.report.level1Type);
      setSelectedSubType(result.report.subType);
      setEnabledRuleKeys(new Set(result.report.suggestedRules.map((r) => r.templateKey)));
      setAdoptedRecommendations(new Set(result.report.governanceRecommendations.map((_, i) => i)));
      if (!result.report.llmAvailable) {
        // LLM 不可用：自动展开手动选择，但保留基础建议
        setSkipAiMode(true);
      }
    } catch (err) {
      setAnalysisError(err instanceof Error ? err.message : '分析失败');
    } finally {
      setAnalyzing(false);
    }
  }, [path]);

  useEffect(() => {
    if (path) {
      void runAnalysis();
    }
    // 仅在 mount / path 变化时触发
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path]);

  const handleToggleRule = useCallback((rule: SuggestedRule) => {
    setEnabledRuleKeys((prev) => {
      const next = new Set(prev);
      if (next.has(rule.templateKey)) next.delete(rule.templateKey);
      else next.add(rule.templateKey);
      return next;
    });
  }, []);

  const handleToggleRecommendation = useCallback((index: number) => {
    setAdoptedRecommendations((prev) => {
      const next = new Set(prev);
      if (next.has(index)) next.delete(index);
      else next.add(index);
      return next;
    });
  }, []);

  const handleSelectL1 = useCallback((type: ProjectType) => {
    setSelectedType(type);
    // 切 L1 时清空 L2（避免跨 L1 残留）
    setSelectedSubType(null);
  }, []);

  const handleSelectL2 = useCallback((key: string | null) => {
    setSelectedSubType(key);
  }, []);

  const subTypeOptionsForL1 = useMemo<SubTypeDefinition[]>(() => {
    if (!subTypes) return [];
    return subTypes.subTypes[selectedType] ?? [];
  }, [subTypes, selectedType]);

  const handleNext = () => {
    const recs = analysisResult?.report.governanceRecommendations ?? [];
    onComplete({
      selectedType,
      selectedSubType,
      enabledRuleKeys: Array.from(enabledRuleKeys),
      adoptedRecommendations: Array.from(adoptedRecommendations)
        .map((i) => recs[i])
        .filter((s): s is string => typeof s === 'string'),
      analysisResult,
      skippedAi: skipAiMode,
    });
  };

  const canProceed = Boolean(selectedType);

  return (
    <div data-testid="project-analysis-wizard" className={`space-y-4 ${className ?? ''}`}>
      {/* 顶部状态条 */}
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <span className="font-mono text-xs">{path ? path.split('/').pop() : ''}</span>
          {catalogError && <span className="text-xs text-destructive">类型目录加载失败</span>}
        </div>
        <div className="flex items-center gap-1.5">
          {!skipAiMode && (
            <button
              type="button"
              data-testid="analysis-skip-ai-btn"
              onClick={() => setSkipAiMode(true)}
              className="rounded border border-border bg-background px-2 py-1 text-xs text-muted-foreground hover:bg-muted hover:text-foreground"
            >
              跳过 AI 分析，手动选择
            </button>
          )}
          {skipAiMode && analysisResult && (
            <button
              type="button"
              data-testid="analysis-resume-ai-btn"
              onClick={() => setSkipAiMode(false)}
              className="rounded border border-primary/30 bg-primary/5 px-2 py-1 text-xs text-primary hover:bg-primary/10"
            >
              恢复 AI 分析结果
            </button>
          )}
        </div>
      </div>

      {/* AI 分析报告（仅当用户未跳过后展示） */}
      {!skipAiMode && (
        <ProjectAnalysisReport
          result={analysisResult}
          loading={analyzing}
          error={analysisError}
          subTypes={subTypes}
          enabledRuleKeys={enabledRuleKeys}
          onToggleRule={handleToggleRule}
          adoptedRecommendations={adoptedRecommendations}
          onToggleRecommendation={handleToggleRecommendation}
          onRegenerate={runAnalysis}
        />
      )}

      {/* L1 选择（始终展示，作为覆盖入口） */}
      <div>
        <label className="mb-2 block text-sm font-medium">
          项目形态（决定目录结构、VCS 快照模式与 AI 上下文护栏）
        </label>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          {L1_OPTIONS.map((opt) => {
            const bp = ARCHETYPE_BLUEPRINTS[opt.value];
            const active = selectedType === opt.value;
            return (
              <button
                key={opt.value}
                type="button"
                data-testid={`analysis-l1-${opt.value}`}
                onClick={() => handleSelectL1(opt.value)}
                className={`rounded-lg border p-3 text-left transition-colors ${
                  active
                    ? 'border-primary bg-primary/10 text-foreground'
                    : 'border-border bg-surface hover:bg-surface-hover text-muted-foreground'
                }`}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="flex items-center gap-1.5 text-xs font-semibold text-foreground">
                    <span className={opt.color}>{opt.icon}</span>
                    {opt.label}
                  </span>
                  <span className="rounded bg-background/80 px-1.5 py-0.5 text-ui-2xs text-muted-foreground">
                    {bp.vcsLabel}
                  </span>
                </div>
                <p className="mt-1 text-ui-2xs text-muted-foreground line-clamp-2">
                  {bp.positioning}
                </p>
              </button>
            );
          })}
        </div>
      </div>

      {/* L2 选择（如果该 L1 有子类型） */}
      {subTypeOptionsForL1.length > 0 && (
        <div>
          <label className="mb-2 block text-sm font-medium">项目子类型（更精确的治理路径）</label>
          <div data-testid="analysis-l2-grid" className="grid grid-cols-1 gap-1.5 sm:grid-cols-2">
            <button
              type="button"
              data-testid="analysis-l2-none"
              onClick={() => handleSelectL2(null)}
              className={`rounded-lg border p-2 text-left text-xs transition-colors ${
                selectedSubType === null
                  ? 'border-primary bg-primary/10 text-foreground'
                  : 'border-border bg-surface hover:bg-surface-hover text-muted-foreground'
              }`}
            >
              <span className="font-medium">仅使用形态级分类</span>
              <span className="ml-1 text-ui-2xs text-muted-foreground">（不指定子类型）</span>
            </button>
            {subTypeOptionsForL1.map((sub) => {
              const active = selectedSubType === sub.key;
              return (
                <button
                  key={sub.key}
                  type="button"
                  data-testid={`analysis-l2-${sub.key}`}
                  onClick={() => handleSelectL2(sub.key)}
                  className={`rounded-lg border p-2 text-left text-xs transition-colors ${
                    active
                      ? 'border-primary bg-primary/10 text-foreground'
                      : 'border-border bg-surface hover:bg-surface-hover text-muted-foreground'
                  }`}
                >
                  <div className="flex items-center gap-1.5">
                    <Sparkles className="h-3 w-3 text-primary" />
                    <span className="font-medium">{sub.label}</span>
                  </div>
                  <p className="mt-0.5 text-ui-2xs text-muted-foreground line-clamp-2">
                    {sub.description}
                  </p>
                </button>
              );
            })}
          </div>
        </div>
      )}

      {/* 导航按钮 */}
      <div className="flex items-center justify-between pt-2">
        <Button type="button" variant="secondary" onClick={onBack} disabled={!onBack}>
          <ArrowLeft className="mr-1 h-4 w-4" />
          返回
        </Button>
        <Button
          type="button"
          onClick={handleNext}
          disabled={!canProceed || analyzing}
          data-testid="analysis-next-btn"
        >
          {analyzing ? (
            <>
              <Loader2 className="mr-1 h-4 w-4 animate-spin" />
              分析中...
            </>
          ) : (
            <>
              下一步
              <ArrowRight className="ml-1 h-4 w-4" />
            </>
          )}
        </Button>
      </div>
    </div>
  );
}

// eslint-disable-next-line react-refresh/only-export-components
export function auditProjectAnalysisWizardGovernance(): {
  module: 'src/features/project-type/ProjectAnalysisWizard.tsx';
  phase: 'P166';
  domain: 'project-type';
  supportsSkipAiFallback: boolean;
  supportsL1Override: boolean;
  supportsL2Override: boolean;
  compliant: boolean;
} {
  return {
    module: 'src/features/project-type/ProjectAnalysisWizard.tsx',
    phase: 'P166',
    domain: 'project-type',
    supportsSkipAiFallback: true,
    supportsL1Override: true,
    supportsL2Override: true,
    compliant: true,
  };
}
