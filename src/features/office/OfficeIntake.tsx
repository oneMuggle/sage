/**
 * OfficeIntake — 统一导入入口（Phase 0, plan §M1「统一导入与文档库」）。
 *
 * 替代原先按类型拆开的四个 <OfficeFilePicker>（Word / Excel / PPT / PDF）。
 * 现在只有一个入口：
 *
 *   - 点击 → 打开**一个**系统文件对话框，`multiSelections` 开启，
 *     过滤器覆盖全部受支持的扩展名；
 *   - 拖拽 → 接受**多个**文件，扩展名由 Electron 主进程
 *     (`docTypeFromExtension`) 判定，渲染层不再持有扩展名映射表。
 *
 * 设计取舍：
 *   - 扩展名 → docType 的判定只存在于主进程，渲染层不重复实现，
 *     避免两张表漂移；
 *   - 组件本身不碰导入令牌（import token），只负责把"用户选了什么"
 *     交给 hook —— 令牌生命周期仍由 `useOfficeDocuments` 独占；
 *   - 不支持的扩展不在前端静默丢弃：主进程会把它放进 `skipped`，
 *     由页面统一提示。
 */

import { FileStack, Upload } from 'lucide-react';
import { useState, type DragEvent, type ReactNode } from 'react';

import { useI18n } from '../../shared/lib/i18n';

/** 受支持的扩展名（与主进程 `getAllOpenDialogFilters` 保持一致）。 */
export const OFFICE_INTAKE_EXTENSIONS = [
  'pptx',
  'docx',
  'xlsx',
  'pdf',
  'ppt',
  'doc',
  'xls',
  'csv',
] as const;

export interface OfficeIntakeProps {
  /** 当前工作区路径；为空时入口不可用。 */
  workspacePath: string | null;
  /**
   * 点击路径：打开系统多选对话框 → 导入 + 读取。
   * 由 hook 独占导入令牌的生命周期，组件不感知 managed path。
   */
  onPick: () => void | Promise<void>;
  /**
   * 拖拽路径：把每个被拖入文件的操作系统源路径交给调用方。
   * 空数组表示没有可用的文件路径（例如 Web 环境）。
   */
  onDropFiles: (sourcePaths: string[]) => void | Promise<void>;
  /** 覆盖默认的提示文案（例如显示当前支持格式）。 */
  children?: ReactNode;
  disabled?: boolean;
}

// eslint-disable-next-line react-refresh/only-export-components
export function formatOfficeIntakeMarkdown(params: {
  workspacePath: string | null;
  disabled?: boolean;
  error: string | null;
}): string {
  return [
    '# Office 统一导入器状态 (Office Intake)',
    '',
    `- **工作区路径**: ${params.workspacePath || '未选择'}`,
    `- **禁用状态**: ${params.disabled ? '已禁用' : '可用'}`,
    `- **支持格式**: ${OFFICE_INTAKE_EXTENSIONS.map((e) => `.${e}`).join(', ')}`,
    `- **最近错误**: ${params.error || '无'}`,
  ].join('\n');
}

// eslint-disable-next-line react-refresh/only-export-components
export function formatOfficeIntakeJson(params: {
  workspacePath: string | null;
  disabled?: boolean;
  error: string | null;
}): string {
  return JSON.stringify(
    {
      exportedAt: new Date().toISOString(),
      workspacePath: params.workspacePath,
      disabled: Boolean(params.disabled),
      supportedExtensions: [...OFFICE_INTAKE_EXTENSIONS],
      error: params.error,
    },
    null,
    2,
  );
}

export function OfficeIntake({
  workspacePath,
  onPick,
  onDropFiles,
  children,
  disabled,
}: OfficeIntakeProps) {
  const { t } = useI18n();
  const [isDragging, setIsDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleClick = async () => {
    if (disabled || busy) return;
    if (!workspacePath) {
      setError(t('office.intake.noWorkspace'));
      return;
    }
    setError(null);
    setBusy(true);
    try {
      // The hook (onPick → importAndReadMulti) owns the dialog + import +
      // read + complete/discard flow and surfaces its own errors.
      await onPick();
    } finally {
      setBusy(false);
    }
  };

  const handleDragOver = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    if (!isDragging) setIsDragging(true);
  };

  const handleDragLeave = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
  };

  const handleDrop = async (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
    if (disabled || busy) return;
    if (!workspacePath) {
      setError(t('office.intake.noWorkspace'));
      return;
    }
    const files = Array.from(e.dataTransfer.files ?? []);
    if (files.length === 0) return;
    // Dropped files have File.path on Electron; null on web.
    const sourcePaths = files
      .map((file) => (file as File & { path?: string }).path)
      .filter((p): p is string => Boolean(p));
    if (sourcePaths.length === 0) {
      setError(t('office.intake.noFilePath'));
      return;
    }
    setError(null);
    setBusy(true);
    try {
      await onDropFiles(sourcePaths);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      onClick={handleClick}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          void handleClick();
        }
      }}
      className={[
        'flex flex-col items-center justify-center gap-3',
        'p-8 border-2 border-dashed rounded-lg cursor-pointer',
        'transition-colors',
        isDragging
          ? 'border-primary bg-primary/10'
          : 'border-border bg-bg-subtle hover:border-primary/50',
        disabled || busy ? 'opacity-50 cursor-not-allowed' : '',
      ].join(' ')}
      data-testid="office-intake"
    >
      {busy ? (
        <Upload className="w-8 h-8 animate-pulse text-muted" />
      ) : (
        <FileStack className="w-8 h-8 text-muted" />
      )}
      <div className="text-sm font-medium text-text">
        {children ?? t('office.intake.title')}
      </div>
      <div className="text-xs text-muted">{t('office.intake.hint')}</div>
      <div className="flex flex-wrap items-center justify-center gap-1.5">
        {OFFICE_INTAKE_EXTENSIONS.map((ext) => (
          <span
            key={ext}
            className="px-1.5 py-0.5 text-ui-2xs rounded bg-bg-muted text-muted border border-border"
          >
            .{ext}
          </span>
        ))}
      </div>
      <button
        type="button"
        className="px-3 py-1.5 text-xs rounded border border-border bg-bg text-text hover:border-primary/50"
        onClick={(e) => {
          e.stopPropagation();
          void handleClick();
        }}
        disabled={disabled || busy}
        data-testid="office-intake-pick"
      >
        {busy ? t('office.intake.busy') : t('office.intake.button')}
      </button>
      {error && (
        <div className="text-xs text-error" data-testid="office-intake-error">
          {error}
        </div>
      )}
    </div>
  );
}

// eslint-disable-next-line react-refresh/only-export-components
export function auditOfficeIntakeGovernance(): {
  moduleId: string;
  phase: string;
  status: 'ready';
} {
  return {
    moduleId: 'src/features/office/OfficeIntake.tsx',
    phase: 'P165',
    status: 'ready',
  };
}
