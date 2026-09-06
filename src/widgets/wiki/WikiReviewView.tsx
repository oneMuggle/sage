// WikiReviewView - Wiki 内容审核视图
import { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, CheckCircle2, Loader2, RefreshCw, X } from 'lucide-react';

import { useReviewStore } from '../../entities/wiki/review-store';
import type { ReviewItem } from '../../shared/types/wiki';
import { ReviewItemCard } from './ReviewItemCard';

interface WikiReviewViewProps {
  projectPath: string;
}

type TypeFilter = 'all' | 'duplicate' | 'contradiction' | 'missing-page' | 'confirm' | 'suggestion';

const TYPE_FILTERS: { value: TypeFilter; label: string }[] = [
  { value: 'all', label: '全部' },
  { value: 'missing-page', label: '缺页' },
  { value: 'duplicate', label: '重复' },
  { value: 'contradiction', label: '矛盾' },
  { value: 'suggestion', label: '建议' },
  { value: 'confirm', label: '待确认' },
];

function formatLastRun(ts: number | null): string {
  if (!ts) return '从未运行';
  const d = new Date(ts);
  return d.toLocaleString();
}

export function WikiReviewView({ projectPath }: WikiReviewViewProps) {
  const items = useReviewStore((s) => s.items);
  const isLoading = useReviewStore((s) => s.isLoading);
  const lastRunAt = useReviewStore((s) => s.lastRunAt);
  const error = useReviewStore((s) => s.error);
  const runReview = useReviewStore((s) => s.runReview);
  const dismissItem = useReviewStore((s) => s.dismissItem);
  const resolveItem = useReviewStore((s) => s.resolveItem);

  const [filter, setFilter] = useState<TypeFilter>('all');
  const [showResolved, setShowResolved] = useState(false);

  // 首次挂载 + projectPath 变化时自动跑一次
  useEffect(() => {
    if (projectPath) {
      void runReview(projectPath);
    }
  }, [projectPath, runReview]);

  const counts = useMemo(() => {
    const c: Record<string, number> = {
      duplicate: 0,
      contradiction: 0,
      'missing-page': 0,
      confirm: 0,
      suggestion: 0,
    };
    for (const i of items) {
      if (i.type in c) c[i.type] += 1;
    }
    return c;
  }, [items]);

  const visible = useMemo(() => {
    let result: ReviewItem[] = items;
    if (!showResolved) {
      result = result.filter((i) => !i.resolved);
    }
    if (filter !== 'all') {
      result = result.filter((i) => i.type === filter);
    }
    return result;
  }, [items, filter, showResolved]);

  const resolvedCount = useMemo(() => items.filter((i) => i.resolved).length, [items]);

  const handleRun = () => {
    void runReview(projectPath);
  };

  const handleAction = (itemId: string, _actionId: string) => {
    // 简化实现:任何 action 一律标记为 resolved
    resolveItem(itemId);
  };

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* Toolbar */}
      <div className="flex items-center gap-2 border-b border-border px-4 py-3">
        <button
          onClick={handleRun}
          disabled={isLoading}
          className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-sm text-text-inverse hover:bg-primary/90 disabled:opacity-50 transition-colors"
        >
          {isLoading ? (
            <>
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              运行中...
            </>
          ) : (
            <>
              <RefreshCw className="h-3.5 w-3.5" />
              运行审核
            </>
          )}
        </button>

        {resolvedCount > 0 && (
          <label className="ml-2 inline-flex items-center gap-1.5 text-xs text-muted">
            <input
              type="checkbox"
              checked={showResolved}
              onChange={(e) => setShowResolved(e.target.checked)}
              className="rounded border-border"
            />
            显示已解决 ({resolvedCount})
          </label>
        )}

        <div className="ml-auto flex items-center gap-3 text-xs text-muted">
          <span>
            共 {items.length} 项:
            <span className="ml-1 text-purple-500">{counts['missing-page']}</span> /
            <span className="ml-1 text-blue-500">{counts.duplicate}</span> /
            <span className="ml-1 text-red-500">{counts.contradiction}</span> /
            <span className="ml-1 text-green-500">{counts.suggestion}</span> /
            <span className="ml-1 text-yellow-500">{counts.confirm}</span>
          </span>
          <span className="text-muted/70">上次: {formatLastRun(lastRunAt)}</span>
        </div>
      </div>

      {/* Type filter */}
      <div className="flex items-center gap-1 border-b border-border px-4 py-2">
        {TYPE_FILTERS.map((f) => (
          <button
            key={f.value}
            onClick={() => setFilter(f.value)}
            data-active={filter === f.value}
            className={`rounded-md px-3 py-1 text-xs transition-colors ${
              filter === f.value
                ? 'bg-primary text-text-inverse'
                : 'text-muted hover:bg-bg-muted hover:text-text'
            }`}
          >
            {f.label}
          </button>
        ))}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-auto px-4 py-4">
        {error && (
          <div className="mb-3 flex items-start gap-2 rounded-md border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-700">
            <AlertTriangle className="mt-0.5 h-4 w-4 flex-shrink-0" />
            <div className="flex-1">
              <p className="font-medium">审核失败</p>
              <p className="text-xs">{error}</p>
            </div>
          </div>
        )}

        {isLoading && items.length === 0 && (
          <div className="flex h-full items-center justify-center text-muted text-sm">
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            正在扫描 Wiki 内容...
          </div>
        )}

        {!isLoading && visible.length === 0 && (
          <div className="flex h-full flex-col items-center justify-center text-muted">
            <CheckCircle2 className="mb-2 h-8 w-8 text-green-500" />
            <p className="text-sm">
              {items.length === 0 ? '尚未运行审核,或项目完全合规' : '当前筛选下无待审项'}
            </p>
          </div>
        )}

        <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
          {visible.map((item) => (
            <div key={item.id} className="relative">
              <button
                type="button"
                onClick={() => dismissItem(item.id)}
                title="忽略此项"
                className="absolute right-2 top-2 z-10 rounded p-1 text-muted/70 hover:text-text hover:bg-bg-muted transition-colors"
              >
                <X className="h-3.5 w-3.5" />
              </button>
              <ReviewItemCard item={item} onAction={handleAction} />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
