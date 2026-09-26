/**
 * WebSearchToolRenderer — 专用 web_search/search_web 工具卡片。
 *
 * 显示: 搜索查询（搜索图标 + 查询文本）+ 结果摘要（从 result 解析条目数）。
 */

import { Globe } from 'lucide-react';

import type { ToolCall } from '../../../shared/lib/store';
import { ToolCallCard } from './ToolCallCard';

export function WebSearchToolRenderer({ tc }: { tc: ToolCall }) {
  const query = String(tc.args.query ?? '');
  const result = typeof tc.result === 'string' ? tc.result : '';

  // 尝试从结果推断条目数（JSON 数组 or "Found N results" 文本）
  let resultCount: number | null = null;
  try {
    const parsed = JSON.parse(result);
    if (Array.isArray(parsed)) resultCount = parsed.length;
  } catch {
    const match = result.match(/(\d+)\s+results?/i);
    if (match) resultCount = parseInt(match[1], 10);
  }

  return (
    <ToolCallCard
      tc={tc}
      title={
        <span className="flex items-center gap-1.5">
          <Globe className="w-3.5 h-3.5 text-primary shrink-0" />
          <span className="font-medium">Search</span>
          <span className="text-text truncate max-w-[200px]" title={query}>
            {query}
          </span>
        </span>
      }
      summary={
        resultCount !== null ? (
          <span className="text-[10px]">{resultCount} results</span>
        ) : undefined
      }
      defaultCollapsed
    >
      <div className="text-[11px] text-text-secondary py-0.5">
        <span className="text-text-muted">Query: </span>
        <span className="text-text">{query}</span>
      </div>
    </ToolCallCard>
  );
}
