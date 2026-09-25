/**
 * 类型自动检测预览组件 (2026-09-25)
 *
 * 项目类型分类系统 - Phase 9.4.2
 * 展示自动检测到的项目类型、置信度、检测信号列表。
 * 可嵌入 ProjectCreationWizard 或独立使用。
 */

import { Sparkles, CheckCircle2, AlertCircle, Loader2 } from 'lucide-react';
import type { ProjectType, ProjectTypeDetectionResult } from '../../shared/api';

export interface TypeDetectionPreviewProps {
  /** 检测结果，null 表示未检测或检测中 */
  result: ProjectTypeDetectionResult | null;
  /** 是否正在检测 */
  loading?: boolean;
  /** 检测错误信息 */
  error?: string | null;
  /** 当前选中的类型（用于高亮匹配项） */
  selectedType?: ProjectType | null;
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
  className,
}: TypeDetectionPreviewProps) {
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

  return (
    <div
      className={`rounded-lg border p-3 ${
        isMatch
          ? 'border-blue-200 bg-blue-50 dark:border-blue-800 dark:bg-blue-950'
          : 'border-border bg-muted/30'
      } ${className ?? ''}`}
    >
      <div className="flex items-center gap-2">
        <Sparkles className={`h-4 w-4 ${detectedColor}`} />
        <span className="text-sm font-medium">
          自动检测：
          <span className={detectedColor}>{detectedLabel}</span>
        </span>
        <span className="text-xs text-muted-foreground">(置信度 {confidencePercent}%)</span>
        {isMatch && <CheckCircle2 className="ml-auto h-4 w-4 text-green-500" />}
      </div>

      {result.signals.length > 0 && (
        <div className="mt-2 space-y-1">
          <div className="text-xs font-medium text-muted-foreground">检测依据：</div>
          <ul className="space-y-0.5">
            {result.signals.map((signal, idx) => (
              <li key={idx} className="text-xs text-muted-foreground">
                • {signal}
              </li>
            ))}
          </ul>
        </div>
      )}

      {confidencePercent < 50 && (
        <div className="mt-2 text-xs text-amber-600 dark:text-amber-400">
          置信度较低，建议手动确认项目类型
        </div>
      )}
    </div>
  );
}
