interface ResizeDividerProps {
  onMouseDown: (e: React.MouseEvent) => void;
}

export function ResizeDivider({ onMouseDown }: ResizeDividerProps) {
  return (
    <div
      onMouseDown={onMouseDown}
      className="w-1 cursor-col-resize hover:bg-primary/30 active:bg-primary/50 transition-colors flex-shrink-0 relative group"
      role="separator"
      aria-orientation="vertical"
    >
      {/* 扩大点击区域 */}
      <div className="absolute inset-y-0 -left-1 -right-1" />
    </div>
  );
}

export interface ResizeDividerAuditInput {
  minWidthPx: number;
  maxWidthPx: number;
  proposedWidthPx: number;
  isDragging: boolean;
}

export interface ResizeDividerAuditReport {
  clampedWidthPx: number;
  withinBounds: boolean;
  isDragging: boolean;
  healthy: boolean;
  issueCodes: string[];
}

// eslint-disable-next-line react-refresh/only-export-components
export function evaluateResizeDividerGovernanceAudit(
  input: ResizeDividerAuditInput,
): ResizeDividerAuditReport {
  const issueCodes: string[] = [];
  if (input.minWidthPx <= 0 || input.maxWidthPx <= input.minWidthPx) {
    issueCodes.push('RESIZE_DIVIDER_BOUNDS_INVALID');
  }
  const withinBounds =
    input.proposedWidthPx >= input.minWidthPx && input.proposedWidthPx <= input.maxWidthPx;
  if (!withinBounds) {
    issueCodes.push('RESIZE_DIVIDER_WIDTH_CLAMPED');
  }
  const safeMin = Math.max(1, Math.trunc(input.minWidthPx));
  const safeMax = Math.max(safeMin, Math.trunc(input.maxWidthPx));
  const clampedWidthPx = Math.max(safeMin, Math.min(safeMax, Math.trunc(input.proposedWidthPx)));
  return {
    clampedWidthPx,
    withinBounds,
    isDragging: input.isDragging,
    healthy: issueCodes.length === 0,
    issueCodes,
  };
}
