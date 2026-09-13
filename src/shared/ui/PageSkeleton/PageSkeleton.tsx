import clsx from 'clsx';

/**
 * 页面级骨架屏 — lazy 路由 chunk 加载期间的 Suspense fallback。
 *
 * 替代此前 App.tsx 的空 div fallback：空 div 会让切页瞬间出现「内容区整块
 * 白屏」，骨架屏保持视觉连续性。结构模拟常见页面布局（标题 + 说明 + 内容块），
 * 纯占位无交互。样式约定对齐 LoadingState skeleton variant（bg-line + pulse）。
 */
export function PageSkeleton({ className }: { className?: string }) {
  return (
    <div
      role="status"
      aria-live="polite"
      aria-label="页面加载中"
      data-testid="page-skeleton"
      className={clsx('flex-1 overflow-hidden p-6', className)}
    >
      <div className="h-6 w-44 rounded bg-line animate-pulse" />
      <div className="mt-3 h-4 w-64 rounded bg-line animate-pulse" />
      <div className="mt-6 space-y-3">
        <div className="h-28 rounded bg-line animate-pulse" />
        <div className="h-28 rounded bg-line animate-pulse" style={{ width: '92%' }} />
        <div className="h-28 rounded bg-line animate-pulse" style={{ width: '96%' }} />
      </div>
    </div>
  );
}
