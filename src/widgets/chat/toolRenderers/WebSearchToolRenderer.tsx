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
          <span className="text-ui-xs">{resultCount} results</span>
        ) : undefined
      }
      defaultCollapsed
    >
      <div className="text-ui-2xs text-text-secondary py-0.5">
        <span className="text-text-muted">Query: </span>
        <span className="text-text">{query}</span>
      </div>
    </ToolCallCard>
  );
}

export interface WebSearchToolRendererAuditInput {
  queryText: string;
  resultCount: number | null;
  searchCompleted: boolean;
  latencyMs: number;
}

export interface WebSearchToolRendererAuditReport {
  hasQuery: boolean;
  normalizedResultCount: number;
  searchCompleted: boolean;
  healthy: boolean;
  issueCodes: string[];
}

// eslint-disable-next-line react-refresh/only-export-components
export function evaluateWebSearchToolRendererGovernanceAudit(
  input: WebSearchToolRendererAuditInput,
): WebSearchToolRendererAuditReport {
  const issueCodes: string[] = [];
  const hasQuery = input.queryText.trim().length > 0;
  if (!hasQuery) {
    issueCodes.push('WEB_SEARCH_QUERY_EMPTY');
  }
  const normalizedResultCount =
    input.resultCount === null ? 0 : Math.max(0, Math.trunc(input.resultCount));
  if (input.resultCount !== null && input.resultCount < 0) {
    issueCodes.push('WEB_SEARCH_RESULT_COUNT_NEGATIVE');
  }
  if (!input.searchCompleted) {
    issueCodes.push('WEB_SEARCH_INCOMPLETE');
  }
  if (!Number.isFinite(input.latencyMs) || input.latencyMs < 0 || input.latencyMs > 60000) {
    issueCodes.push('WEB_SEARCH_LATENCY_OUT_OF_RANGE');
  }
  return {
    hasQuery,
    normalizedResultCount,
    searchCompleted: input.searchCompleted,
    healthy: issueCodes.length === 0,
    issueCodes,
  };
}
