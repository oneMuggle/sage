// Lint View - 文档质量检查视图
import { Play, Filter } from 'lucide-react';
import { useState } from 'react';

import { useLintStore } from '../../entities/wiki/lint-store';
import { mockLintItems } from '../../entities/wiki/mock-data';

import { LintItemCard } from './LintItemCard';

export function LintView() {
  const items = useLintStore((s) => s.items);
  const setItems = useLintStore((s) => s.setItems);
  const removeItem = useLintStore((s) => s.removeItem);
  const setLastRunAt = useLintStore((s) => s.setLastRunAt);

  const [filter, setFilter] = useState<'all' | 'warning' | 'info'>('all');

  // 初始化模拟数据
  const handleRunLint = () => {
    setItems(mockLintItems);
    setLastRunAt(Date.now());
  };

  const handleFix = (id: string) => {
    // 模拟修复操作
    removeItem(id);
  };

  const handleDismiss = (id: string) => {
    removeItem(id);
  };

  // 过滤项目
  const filteredItems = items.filter((item) => {
    if (filter === 'all') return true;
    return item.severity === filter;
  });

  const warningCount = items.filter((i) => i.severity === 'warning').length;
  const infoCount = items.filter((i) => i.severity === 'info').length;

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border px-4 py-3 bg-surface">
        <div>
          <h2 className="text-lg font-semibold text-text">文档质量检查</h2>
          <p className="text-xs text-muted mt-0.5">检查孤立页面、断链、语义问题等</p>
        </div>
        <button
          onClick={handleRunLint}
          className="flex items-center gap-2 px-4 py-2 bg-primary text-text-inverse rounded-md hover:bg-primary-hover transition-colors"
        >
          <Play className="h-4 w-4" />
          运行检查
        </button>
      </div>

      {/* Filter bar */}
      {items.length > 0 && (
        <div className="flex items-center gap-3 border-b border-border px-4 py-2 bg-surface">
          <Filter className="h-4 w-4 text-muted" />
          <div className="flex items-center gap-2">
            <button
              onClick={() => setFilter('all')}
              className={`px-3 py-1 text-xs rounded-radius-sm transition-colors ${
                filter === 'all' ? 'bg-primary/10 text-primary' : 'text-muted hover:bg-bg-muted'
              }`}
            >
              全部 ({items.length})
            </button>
            <button
              onClick={() => setFilter('warning')}
              className={`px-3 py-1 text-xs rounded-radius-sm transition-colors ${
                filter === 'warning'
                  ? 'bg-orange-500/10 text-orange-500'
                  : 'text-muted hover:bg-bg-muted'
              }`}
            >
              警告 ({warningCount})
            </button>
            <button
              onClick={() => setFilter('info')}
              className={`px-3 py-1 text-xs rounded-radius-sm transition-colors ${
                filter === 'info' ? 'bg-blue-500/10 text-blue-500' : 'text-muted hover:bg-bg-muted'
              }`}
            >
              信息 ({infoCount})
            </button>
          </div>
        </div>
      )}

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-4">
        {items.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-muted">
            <p className="text-sm">点击"运行检查"开始文档质量检查</p>
            <p className="text-xs mt-1">将检测孤立页面、断链、无出链和语义问题</p>
          </div>
        ) : filteredItems.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-muted">
            <p className="text-sm">没有匹配的项目</p>
          </div>
        ) : (
          <div className="space-y-3">
            {filteredItems.map((item) => (
              <LintItemCard key={item.id} item={item} onFix={handleFix} onDismiss={handleDismiss} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
