/**
 * 类型自动检测预览组件 (2026-09-25; Phase P29 生命周期阶段管线预览、治理套件统计与检测依据导出)
 *
 * 项目类型分类系统 - Phase 9.4.2
 * 展示自动检测到的项目类型、置信度、检测信号列表、推荐阶段管线与治理套件统计，支持一键复制检测依据 Markdown。
 * 可嵌入 ProjectCreationWizard 或独立使用。
 */

import { Sparkles, CheckCircle2, AlertCircle, Loader2, Copy, Check } from 'lucide-react';
import { useState } from 'react';

import type { ProjectType, ProjectTypeDetectionResult } from '../../shared/api';

import { getArchetypeBlueprint } from './archetypeBlueprints';

export interface TypeDetectionPreviewProps {
  /** 检测结果，null 表示未检测或检测中 */
  result: ProjectTypeDetectionResult | null;
  /** 是否正在检测 */
  loading?: boolean;
  /** 检测错误信息 */
  error?: string | null;
  /** 当前选中的类型（用于高亮匹配项） */
  selectedType?: ProjectType | null;
  /** 一键应用检测到的项目类型回调 */
  onApplyDetectedType?: (type: ProjectType) => void;
  /** 自定义 className */
  className?: string;
}

const TYPE_LABELS: Record<ProjectType, string> = {
  coding: '编码',
  research: '科研',
  business: '事务',
  personal: '个人',
};

const TYPE_COLORS: Record<ProjectType, string> = {
  coding: 'text-blue-500',
  research: 'text-purple-500',
  business: 'text-green-500',
  personal: 'text-orange-500',
};

export function TypeDetectionPreview({
  result,
  loading = false,
  error = null,
  selectedType,
  onApplyDetectedType,
  className,
}: TypeDetectionPreviewProps) {
  const [copiedMd, setCopiedMd] = useState(false);
  const [showDetails, setShowDetails] = useState(false);
  const [copiedSuite, setCopiedSuite] = useState(false);
  const [copiedSignalIdx, setCopiedSignalIdx] = useState<number | null>(null);

  if (loading) {
    return (
      <div className={`flex items-center gap-2 text-sm text-muted-foreground ${className ?? ''}`}>
        <Loader2 className="h-4 w-4 animate-spin" />
        正在检测项目类型...
      </div>
    );
  }

  if (error) {
    return (
      <div className={`flex items-center gap-2 text-sm text-destructive ${className ?? ''}`}>
        <AlertCircle className="h-4 w-4" />
        检测失败：{error}
      </div>
    );
  }

  if (!result) {
    return null;
  }

  const detectedLabel = TYPE_LABELS[result.detectedType];
  const detectedColor = TYPE_COLORS[result.detectedType];
  const confidencePercent = Math.round(result.confidence * 100);
  const isMatch = selectedType === result.detectedType;
  const detectedBlueprint = getArchetypeBlueprint(result.detectedType);
  const stagesFlow = detectedBlueprint.stages.map((s) => s.label).join(' → ');

  const handleCopyDetectionMarkdown = async () => {
    const lines = [
      `# 项目形态自动检测报告`,
      `- **检测形态**：${detectedBlueprint.label} (${result.detectedType})`,
      `- **置信度**：${confidencePercent}%`,
      `- **推荐版本策略**：${detectedBlueprint.vcsLabel}`,
      `- **推荐阶段管线**：${stagesFlow}`,
      result.signals.length > 0 ? `- **检测依据**：${result.signals.join('；')}` : '',
    ].filter(Boolean);
    try {
      await navigator.clipboard?.writeText(lines.join('\n'));
      setCopiedMd(true);
      setTimeout(() => setCopiedMd(false), 1800);
    } catch {
      // ignore in test/offline mode
    }
  };

  return (
    <div
      className={`rounded-lg border p-3 ${
        isMatch
          ? 'border-blue-200 bg-blue-50 dark:border-blue-800 dark:bg-blue-950'
          : 'border-border bg-muted/30'
      } ${className ?? ''}`}
    >
      <div className="flex flex-wrap items-center gap-2">
        <Sparkles className={`h-4 w-4 ${detectedColor}`} />
        <span className="text-sm font-medium">
          自动检测：
          <span className={detectedColor}>{detectedLabel}</span>
        </span>
        <span className="text-xs text-muted-foreground">(置信度 {confidencePercent}%)</span>
        <div className="ml-auto flex items-center gap-1.5">
          <button
            type="button"
            data-testid="detection-copy-md-btn"
            onClick={() => void handleCopyDetectionMarkdown()}
            className="inline-flex items-center gap-1 rounded border border-border bg-background px-2 py-0.5 text-ui-2xs text-muted-foreground hover:bg-muted hover:text-foreground"
            title="复制自动检测报告 Markdown"
          >
            {copiedMd ? (
              <>
                <Check className="h-3 w-3 text-emerald-500" />
                已复制
              </>
            ) : (
              <>
                <Copy className="h-3 w-3" />
                复制检测依据
              </>
            )}
          </button>
          {isMatch ? (
            <CheckCircle2 className="h-4 w-4 text-green-500" />
          ) : (
            onApplyDetectedType && (
              <button
                type="button"
                data-testid="apply-detected-type-btn"
                onClick={() => onApplyDetectedType(result.detectedType)}
                className="rounded border border-primary/40 bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary hover:bg-primary/20"
              >
                一键采用检测形态
              </button>
            )
          )}
        </div>
      </div>

      {result.signals.length > 0 && (
        <div className="mt-2 space-y-1">
          <div className="text-xs font-medium text-muted-foreground">检测依据：</div>
          <ul className="space-y-0.5">
            {result.signals.map((signal, idx) => (
              <li
                key={idx}
                data-testid={`detection-signal-item-${idx}`}
                className="flex items-center justify-between gap-2 text-xs text-muted-foreground"
              >
                <span>• {signal}</span>
                <button
                  type="button"
                  data-testid={`detection-copy-signal-${idx}`}
                  onClick={async () => {
                    try {
                      await navigator.clipboard?.writeText(signal);
                      setCopiedSignalIdx(idx);
                      setTimeout(() => setCopiedSignalIdx(null), 1500);
                    } catch {
                      // ignore in test/offline mode
                    }
                  }}
                  className="rounded border border-border bg-background px-1.5 py-0.5 text-ui-2xs text-muted-foreground hover:bg-muted hover:text-foreground"
                >
                  {copiedSignalIdx === idx ? '已复制' : '复制依据'}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div
        className="mt-2 rounded border border-border/60 bg-background/60 p-2 text-xs text-muted-foreground space-y-1"
        data-testid="detection-blueprint-preview"
      >
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            推荐版本策略：<span className="font-medium text-foreground">{detectedBlueprint.vcsLabel}</span>
          </div>
          <span
            className="rounded bg-primary/10 px-1.5 py-0.5 text-ui-2xs font-medium text-primary"
            data-testid="detection-governance-stats"
          >
            {detectedBlueprint.recommendedMilestones.length} 个推荐里程碑 · {detectedBlueprint.subTemplates.length} 套细分规范包
          </span>
        </div>
        <div data-testid="detection-stages-preview">
          推荐阶段管线：<span className="font-medium text-foreground">{stagesFlow}</span>
        </div>
        <div className="flex flex-wrap items-center gap-1">
          <span>推荐标准目录：</span>
          {detectedBlueprint.directories.map((dir) => (
            <span
              key={dir}
              className="rounded border border-border bg-muted/40 px-1.5 py-0.5 font-mono text-ui-2xs text-foreground"
            >
              {dir}/
            </span>
          ))}
          <div className="ml-auto flex items-center gap-1">
          <button
            type="button"
            data-testid="detection-copy-suite-btn"
            onClick={async () => {
              const md = [
                `# ${detectedBlueprint.label} 推荐治理清单`,
                `- **标准目录**：${detectedBlueprint.directories.join('、')}`,
                `- **规范预设包**：${detectedBlueprint.subTemplates.map((t) => t.label).join(' · ')}`,
                `- **默认里程碑**：${detectedBlueprint.recommendedMilestones.map((m) => m.title).join(' → ')}`,
              ].join('\n');
              try {
                await navigator.clipboard?.writeText(md);
                setCopiedSuite(true);
                setTimeout(() => setCopiedSuite(false), 1500);
              } catch {
                // ignore in test/offline mode
              }
            }}
            className="rounded border border-border bg-background px-1.5 py-0.5 text-ui-2xs text-foreground hover:bg-muted"
          >
            {copiedSuite ? '已复制清单' : '复制治理清单'}
          </button>
          <button
            type="button"
            data-testid="detection-details-toggle-btn"
            onClick={() => setShowDetails((v) => !v)}
            className="rounded border border-primary/30 bg-primary/5 px-1.5 py-0.5 text-ui-2xs font-medium text-primary hover:bg-primary/10"
          >
            {showDetails ? '收起推荐规范与里程碑' : '展开推荐规范与里程碑'}
          </button>
          </div>
        </div>
        {showDetails && (
          <div
            className="mt-1.5 border-t border-border/60 pt-1.5 space-y-1 text-ui-2xs"
            data-testid="detection-details-panel"
          >
            <div>
              <span className="text-muted-foreground">推荐规范包：</span>
              <span className="font-medium text-foreground">
                {detectedBlueprint.subTemplates.map((t) => t.label).join(' · ')}
              </span>
            </div>
            <div>
              <span className="text-muted-foreground">默认里程碑：</span>
              <span className="font-medium text-foreground">
                {detectedBlueprint.recommendedMilestones.map((m) => m.title).join(' → ')}
              </span>
            </div>
          </div>
        )}
      </div>

      {confidencePercent < 50 && (
        <div className="mt-2 text-xs text-amber-600 dark:text-amber-400">
          置信度较低，建议手动确认项目类型
        </div>
      )}
    </div>
  );
}
