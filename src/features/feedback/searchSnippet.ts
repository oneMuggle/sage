// src/features/feedback/searchSnippet.ts
//
// 搜索结果摘要：把消息正文压成单行，并把命中位置放进可视窗口中间。
// 纯函数，便于单测（不依赖 IPC / 组件）。

export const SEARCH_SNIPPET_MAX_CHARS = 80;

export function buildSearchSnippet(
  body: string,
  query: string,
  maxChars: number = SEARCH_SNIPPET_MAX_CHARS,
): string {
  const flat = body.replace(/\s+/g, ' ').trim();
  if (flat.length <= maxChars) return flat;

  const needle = query.trim().toLowerCase();
  const idx = needle ? flat.toLowerCase().indexOf(needle) : -1;
  if (idx < 0) return `${flat.slice(0, maxChars)}…`;

  const start = Math.max(0, Math.min(idx - Math.floor(maxChars / 3), flat.length - maxChars));
  const end = Math.min(flat.length, start + maxChars);
  return `${start > 0 ? '…' : ''}${flat.slice(start, end)}${end < flat.length ? '…' : ''}`;
}
