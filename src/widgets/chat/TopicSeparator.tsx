/**
 * Task 5 (2026-09-17): 话题分隔线 —— 在聊天流中标记"上下文已在此处重置"。
 * 居中文字 + 两侧水平线的经典分隔线样式。
 */
export function TopicSeparator({ content }: { content?: string | null }) {
  return (
    <div className="flex items-center my-4 text-xs text-text-secondary select-none">
      <div className="flex-1 border-t border-border" />
      <span className="px-3 whitespace-nowrap">
        {content || '上下文已在此处重置'}
      </span>
      <div className="flex-1 border-t border-border" />
    </div>
  );
}
