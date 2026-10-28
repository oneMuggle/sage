/**
 * ExecutionModePicker — 执行模式选择对话框（2026-10-28）。
 *
 * 当后端执行模式分类器返回 `ask_user`（confidence < 0.7）时，
 * 弹出此对话框让用户选择最佳执行模式。
 *
 * 降级纪律：用户关闭对话框或拒绝选择 → 默认停止执行，保留 plan 待审阅。
 */
import { useCallback } from 'react';

export type ExecutionMode = 'single' | 'multi';

export interface ExecutionModePickerProps {
  /** 是否显示对话框 */
  open: boolean;
  /** 选择完成回调：single / multi */
  onSelect: (mode: ExecutionMode) => void;
  /** 关闭回调（用户取消） */
  onClose: () => void;
  /** 可选：分类器提供的判断依据 */
  reasoning?: string;
}

export function ExecutionModePicker({
  open,
  onSelect,
  onClose,
  reasoning,
}: ExecutionModePickerProps) {
  const handleSingle = useCallback(() => {
    onSelect('single');
    onClose();
  }, [onSelect, onClose]);

  const handleMulti = useCallback(() => {
    onSelect('multi');
    onClose();
  }, [onSelect, onClose]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="bg-bg rounded-lg shadow-xl max-w-md w-full mx-4 p-6">
        <h3 className="text-lg font-semibold mb-2">选择执行模式</h3>
        <p className="text-sm text-text-secondary mb-4">
          任务复杂度 ambiguous，请选择最适合的执行模式。
        </p>
        {reasoning && (
          <div className="mb-4 p-3 rounded bg-bg-muted/40 text-xs text-text-secondary">
            <span className="font-medium">分类依据：</span>
            {reasoning}
          </div>
        )}
        <div className="space-y-3">
          <button
            type="button"
            onClick={handleSingle}
            className="w-full px-4 py-3 text-left rounded border border-border hover:border-primary hover:bg-primary/5 transition-colors"
          >
            <div className="font-medium">单 agent（串行）</div>
            <div className="text-xs text-text-secondary mt-1">
              适用于步骤少、强依赖链、单文件修改的任务
            </div>
          </button>
          <button
            type="button"
            onClick={handleMulti}
            className="w-full px-4 py-3 text-left rounded border border-border hover:border-primary hover:bg-primary/5 transition-colors"
          >
            <div className="font-medium">编排模式（并行）</div>
            <div className="text-xs text-text-secondary mt-1">
              适用于步骤多、多文件、有并行可能的任务
            </div>
          </button>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="w-full mt-4 px-4 py-2 text-sm text-text-secondary hover:text-text-primary transition-colors"
        >
          取消（保留 plan 待审阅）
        </button>
      </div>
    </div>
  );
}
