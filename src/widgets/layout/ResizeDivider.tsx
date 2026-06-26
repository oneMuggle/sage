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
