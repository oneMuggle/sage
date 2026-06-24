// Review View - 审核队列视图
import { CheckCircle2, Filter } from 'lucide-react';
import { useState } from 'react';

import { useReviewStore } from '../../entities/wiki/review-store';
import { mockReviewItems } from '../../entities/wiki/mock-data';
import { ReviewItemCard } from './ReviewItemCard';

export function ReviewView() {
  const items = useReviewStore((s) => s.items);
  const setItems = useReviewStore((s) => s.setItems);
  const resolveItem = useReviewStore((s) => s.resolveItem);
  const clearResolved = useReviewStore((s) => s.clearResolved);

  const [typeFilter, setTypeFilter] = useState<string>('all');
  const [statusFilter, setStatusFilter] = useState<'all' | 'pending' | 'resolved'>('all');

  // 初始化模拟数据
  const handleLoadMockData = () => {
    setItems(mockReviewItems);
  };

  const handleAction = (itemId: string, actionId: string) => {
    // 模拟操作处理
    if (actionId === 'dismiss') {
      resolveItem(itemId);
    } else {
      // 其他操作暂时只是标记为已解决
      resolveItem(itemId);
    }
  };

  // 过滤项目
  const filteredItems = items.filter((item) => {
    if (typeFilter !== 'all' && item.type !== typeFilter) return false;
    if (statusFilter === 'pending' && item.resolved) return false;
    if (statusFilter === 'resolved' && !item.resolved) return false;
    return true;
  });

  const pendingCount = items.filter((i) => !i.resolved).length;
  const resolvedCount = items.filter((i) => i.resolved).length;

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border px-4 py-3 bg-surface">
        <div>
          <h2 className="text-lg font-semibold text-text">审核队列</h2>
          <p className="text-xs text-muted mt-0.5">处理矛盾、重复、缺失页面等问题</p>
        </div>
        <div className="flex items-center gap-2">
          {resolvedCount > 0 && (
            <button
              onClick={clearResolved}
              className="flex items-center gap-2 px-3 py-1.5 text-xs rounded-radius-sm border border-border text-muted hover:bg-bg-muted transition-colors"
            >
              <CheckCircle2 className="h-3 w-3" />
              清除已解决
            </button>
          )}
          <button
            onClick={handleLoadMockData}
            className="px-4 py-2 bg-primary text-text-inverse rounded-md hover:bg-primary-hover transition-colors"
          >
            加载示例数据
          </button>
        </div>
      </div>

      {/* Filter bar */}
      {items.length > 0 && (
        <div className="flex items-center gap-4 border-b border-border px-4 py-2 bg-surface">
          <Filter className="h-4 w-4 text-muted" />

          {/* Type filter */}
          <div className="flex items-center gap-2">
            <span className="text-xs text-muted">类型:</span>
            <select
              value={typeFilter}
              onChange={(e) => setTypeFilter(e.target.value)}
              className="text-xs rounded-radius-sm border border-border bg-surface px-2 py-1 text-text focus:outline-none focus:ring-2 focus:ring-primary/20"
            >
              <option value="all">全部</option>
              <option value="contradiction">矛盾</option>
              <option value="duplicate">重复</option>
              <option value="missing-page">缺页</option>
              <option value="confirm">待确认</option>
              <option value="suggestion">建议</option>
            </select>
          </div>

          {/* Status filter */}
          <div className="flex items-center gap-2">
            <span className="text-xs text-muted">状态:</span>
            <button
              onClick={() => setStatusFilter('all')}
              className={`px-3 py-1 text-xs rounded-radius-sm transition-colors ${
                statusFilter === 'all'
                  ? 'bg-primary/10 text-primary'
                  : 'text-muted hover:bg-bg-muted'
              }`}
            >
              全部 ({items.length})
            </button>
            <button
              onClick={() => setStatusFilter('pending')}
              className={`px-3 py-1 text-xs rounded-radius-sm transition-colors ${
                statusFilter === 'pending'
                  ? 'bg-orange-500/10 text-orange-500'
                  : 'text-muted hover:bg-bg-muted'
              }`}
            >
              待处理 ({pendingCount})
            </button>
            <button
              onClick={() => setStatusFilter('resolved')}
              className={`px-3 py-1 text-xs rounded-radius-sm transition-colors ${
                statusFilter === 'resolved'
                  ? 'bg-green-500/10 text-green-500'
                  : 'text-muted hover:bg-bg-muted'
              }`}
            >
              已解决 ({resolvedCount})
            </button>
          </div>
        </div>
      )}

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-4">
        {items.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-muted">
            <p className="text-sm">审核队列为空</p>
            <p className="text-xs mt-1">点击"加载示例数据"查看演示</p>
          </div>
        ) : filteredItems.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-muted">
            <p className="text-sm">没有匹配的项目</p>
          </div>
        ) : (
          <div className="space-y-3">
            {filteredItems.map((item) => (
              <ReviewItemCard key={item.id} item={item} onAction={handleAction} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
