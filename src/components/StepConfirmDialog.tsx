/**
 * ``StepConfirmDialog`` — 步骤确认对话框（Phase 3 Week 4, 2026-10-28）。
 *
 * 当 plan 执行到标记为 `auto_confirm` 的步骤时弹出，展示：
 * - 当前步骤描述 + 影响预估
 * - 上一步输出摘要（如有）
 * - 下一步预览（如有）
 *
 * 三个按钮：
 * - [继续] → 执行当前步骤
 * - [跳过此步] → 标记 skipped，继续下一步
 * - [终止全部] → 取消整个 plan
 */
import { AlertTriangle, Play, SkipForward, XCircle } from 'lucide-react';

import type { StepConfirmAction, StepConfirmInfo } from '../shared/api/types/planModeTypes';

export type { StepConfirmAction, StepConfirmInfo };

// ============================================================================
// Types
// ============================================================================

export interface StepConfirmDialogProps {
  step: StepConfirmInfo;
  onConfirm: (action: StepConfirmAction) => void;
}

// ============================================================================
// Category label mapping
// ============================================================================

const CATEGORY_LABELS: Record<string, string> = {
  file_delete: '文件删除',
  external_api: '外部 API 调用',
  db_write: '数据库写操作',
  privileged: '特权操作',
};

function categoryLabel(cat: string): string {
  return CATEGORY_LABELS[cat] || cat;
}

// ============================================================================
// Component
// ============================================================================

export function StepConfirmDialog({ step, onConfirm }: StepConfirmDialogProps) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
      data-testid="step-confirm-dialog-overlay"
    >
      <div
        className="bg-bg-card border rounded-lg shadow-lg max-w-lg w-full mx-4 p-6 space-y-4"
        data-testid="step-confirm-dialog"
      >
        {/* Header */}
        <div className="flex items-center gap-3">
          <AlertTriangle className="w-6 h-6 text-amber-500 flex-shrink-0" />
          <h2 className="text-lg font-semibold">步骤确认</h2>
        </div>

        {/* Current step */}
        <div className="space-y-2">
          <div className="text-sm font-medium text-text-secondary">当前步骤</div>
          <div className="p-3 bg-bg-hover rounded text-sm" data-testid="step-goal">
            {step.goal}
          </div>
        </div>

        {/* Impact */}
        {step.impact && (
          <div className="space-y-1">
            <div className="text-sm font-medium text-text-secondary">影响预估</div>
            <div
              className="p-3 bg-amber-500/10 border border-amber-500/30 rounded text-sm text-amber-700 dark:text-amber-300"
              data-testid="step-impact"
            >
              {step.impact}
            </div>
          </div>
        )}

        {/* Categories */}
        {step.categories && step.categories.length > 0 && (
          <div className="space-y-1">
            <div className="text-sm font-medium text-text-secondary">触发规则</div>
            <div className="flex flex-wrap gap-2" data-testid="step-categories">
              {step.categories.map((cat) => (
                <span
                  key={cat}
                  className="px-2 py-0.5 bg-bg-active text-text-secondary text-xs rounded"
                >
                  {categoryLabel(cat)}
                </span>
              ))}
            </div>
          </div>
        )}

        {/* Previous output */}
        {step.previousOutput && (
          <div className="space-y-1">
            <div className="text-sm font-medium text-text-secondary">上一步输出</div>
            <div
              className="p-3 bg-bg-hover rounded text-sm text-text-muted max-h-24 overflow-y-auto"
              data-testid="step-previous-output"
            >
              {step.previousOutput}
            </div>
          </div>
        )}

        {/* Next step preview */}
        {step.nextStepPreview && (
          <div className="space-y-1">
            <div className="text-sm font-medium text-text-secondary">下一步预览</div>
            <div
              className="p-3 bg-bg-hover rounded text-sm text-text-muted italic"
              data-testid="step-next-preview"
            >
              {step.nextStepPreview}
            </div>
          </div>
        )}

        {/* Actions */}
        <div className="flex gap-3 pt-4 border-t">
          <button
            type="button"
            onClick={() => onConfirm('continue')}
            className="flex-1 flex items-center justify-center gap-2 px-4 py-2 bg-blue-500 text-white rounded hover:bg-blue-600 transition-colors font-medium"
            data-testid="step-confirm-continue"
          >
            <Play className="w-4 h-4" />
            继续
          </button>
          <button
            type="button"
            onClick={() => onConfirm('skip')}
            className="flex-1 flex items-center justify-center gap-2 px-4 py-2 bg-bg-hover text-text-secondary rounded hover:bg-bg-active transition-colors"
            data-testid="step-confirm-skip"
          >
            <SkipForward className="w-4 h-4" />
            跳过此步
          </button>
          <button
            type="button"
            onClick={() => onConfirm('abort')}
            className="flex-1 flex items-center justify-center gap-2 px-4 py-2 bg-red-500/10 text-red-600 dark:text-red-400 rounded hover:bg-red-500/20 transition-colors"
            data-testid="step-confirm-abort"
          >
            <XCircle className="w-4 h-4" />
            终止全部
          </button>
        </div>
      </div>
    </div>
  );
}
