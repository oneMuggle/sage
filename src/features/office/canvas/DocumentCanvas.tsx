/**
 * DocumentCanvas — 统一文档画布（/office 文档工作台的中心视图）。
 *
 * 两种形态：
 *   - 空态：渲染 OfficeIntake，导入 / 拖拽入口全部由它自己处理；
 *   - 有文档：渲染 OfficePreviewPanel，并在画布根部接管拖拽 ——
 *     把新文件拖到当前文档上会显示替换遮罩，松手后把操作系统
 *     源路径交给 `onDropFiles`，由页面重新导入并替换当前文档。
 *
 * 拖拽 handlers 只在 `preview` 非空时安装，避免和 OfficeIntake
 * 的 drop 逻辑重复触发。
 */

import { Upload } from 'lucide-react';
import { useEffect, useState, type DragEvent } from 'react';

import { useI18n } from '../../../shared/lib/i18n';
import { OfficeIntake } from '../OfficeIntake';
import { OfficePreviewPanel, type OfficePreviewData } from '../OfficePreviewPanel';

export interface DocumentCanvasProps {
  preview: OfficePreviewData | null;
  workspacePath: string | null;
  onPick?: () => void | Promise<void>;
  onDropFiles?: (sourcePaths: string[]) => void | Promise<void>;
  onEditPreview?: () => void;
  /** 是否有可用的格式转换器（高保真 / PDF 导出开关）。 */
  fidelityAvailable?: boolean;
  /** 就地修改（公式缓存重算 / PDF 表单填充）后重新读取当前文档。 */
  onRefresh?: () => void;
  /** 导入进行中时禁用空态的再次导入。 */
  disabled?: boolean;
}

export function DocumentCanvas({
  preview,
  workspacePath,
  onPick,
  onDropFiles,
  onEditPreview,
  fidelityAvailable,
  onRefresh,
  disabled,
}: DocumentCanvasProps) {
  const { t } = useI18n();
  const [isDragging, setIsDragging] = useState(false);

  // 文档关闭时清掉拖拽态，避免下一份文档打开时遮罩误显示。
  useEffect(() => {
    if (!preview) setIsDragging(false);
  }, [preview]);

  const handleDragEnter = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    if (!isDragging) setIsDragging(true);
  };

  const handleDragOver = (e: DragEvent<HTMLDivElement>) => {
    // 不 preventDefault 浏览器会拒绝 drop。
    e.preventDefault();
    e.stopPropagation();
    if (e.dataTransfer) e.dataTransfer.dropEffect = 'copy';
    if (!isDragging) setIsDragging(true);
  };

  const handleDragLeave = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    // 指针划过子元素也会触发 dragleave；只有真正离开画布才隐藏遮罩。
    if (e.currentTarget.contains(e.relatedTarget as Node | null)) return;
    setIsDragging(false);
  };

  const handleDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
    const sourcePaths = Array.from(e.dataTransfer?.files ?? [])
      .map((file) => (file as File & { path?: string }).path)
      .filter((p): p is string => Boolean(p));
    if (sourcePaths.length > 0) void onDropFiles?.(sourcePaths);
  };

  // 空态由 OfficeIntake 独占拖拽，画布不重复安装 handlers。
  const dragHandlers = preview
    ? {
        onDragEnter: handleDragEnter,
        onDragOver: handleDragOver,
        onDragLeave: handleDragLeave,
        onDrop: handleDrop,
      }
    : {};

  return (
    <div
      className="relative flex-1 flex flex-col"
      data-testid="office-document-canvas"
      {...dragHandlers}
    >
      {preview ? (
        <>
          <OfficePreviewPanel
            preview={preview}
            workspacePath={workspacePath ?? undefined}
            onEditPreview={onEditPreview}
            fidelityAvailable={fidelityAvailable}
            onRefresh={onRefresh}
          />
          {isDragging && (
            <div
              className="pointer-events-none absolute inset-0 z-10 flex flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed border-primary bg-primary/10"
              data-testid="office-document-canvas-drop-overlay"
              aria-hidden="true"
            >
              <Upload className="w-8 h-8 text-primary" />
              <div className="text-sm font-medium text-primary">
                {t('office.canvas.dropToReplace')}
              </div>
            </div>
          )}
        </>
      ) : (
        <OfficeIntake
          workspacePath={workspacePath}
          onPick={onPick ?? (() => {})}
          onDropFiles={onDropFiles ?? (() => {})}
          disabled={disabled}
        />
      )}
    </div>
  );
}
