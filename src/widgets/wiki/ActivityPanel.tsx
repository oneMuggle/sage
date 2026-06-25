// Activity Panel - 操作历史追踪面板
import {
  Activity as ActivityIcon,
  AlertCircle,
  CheckCircle2,
  Database,
  Loader2,
  MessageSquare,
} from 'lucide-react';
import { useState } from 'react';

import { useActivityStore } from '../../entities/wiki/activity-store';
import { mockActivities } from '../../entities/wiki/mock-data';
import type { ActivityItem } from '../../shared/types/wiki';

const TYPE_CONFIG = {
  ingest: {
    icon: Database,
    label: '导入',
    color: 'text-blue-500',
  },
  lint: {
    icon: AlertCircle,
    label: '检查',
    color: 'text-orange-500',
  },
  query: {
    icon: MessageSquare,
    label: '查询',
    color: 'text-purple-500',
  },
};

const STATUS_CONFIG = {
  running: {
    icon: Loader2,
    color: 'text-blue-500',
    label: '进行中',
    animate: true,
  },
  done: {
    icon: CheckCircle2,
    color: 'text-green-500',
    label: '完成',
    animate: false,
  },
  error: {
    icon: AlertCircle,
    color: 'text-red-500',
    label: '失败',
    animate: false,
  },
};

function formatTime(timestamp: number): string {
  const diff = Date.now() - timestamp;
  if (diff < 60000) return '刚刚';
  if (diff < 3600000) return `${Math.floor(diff / 60000)}分钟前`;
  if (diff < 86400000) return `${Math.floor(diff / 3600000)}小时前`;
  return `${Math.floor(diff / 86400000)}天前`;
}

function ActivityRow({ item }: { item: ActivityItem }) {
  const typeConfig = TYPE_CONFIG[item.type];
  const statusConfig = STATUS_CONFIG[item.status];
  const TypeIcon = typeConfig.icon;
  const StatusIcon = statusConfig.icon;

  return (
    <div className="flex items-start gap-2 px-3 py-2 hover:bg-bg-muted transition-colors">
      <TypeIcon className={`h-3.5 w-3.5 mt-0.5 ${typeConfig.color} flex-shrink-0`} />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-1.5">
          <span className="text-xs font-medium text-text">{typeConfig.label}</span>
          <StatusIcon
            className={`h-3 w-3 ${statusConfig.color} ${
              statusConfig.animate ? 'animate-spin' : ''
            }`}
          />
          <span className="text-xs text-muted">{statusConfig.label}</span>
        </div>
        <div className="text-xs text-muted mt-0.5">{formatTime(item.startedAt)}</div>
        {item.filesWritten && item.filesWritten.length > 0 && (
          <div className="text-xs text-primary mt-1 truncate">
            → {item.filesWritten.map((f) => f.split('/').pop()).join(', ')}
          </div>
        )}
        {item.error && <div className="text-xs text-red-500 mt-1 truncate">错误: {item.error}</div>}
      </div>
    </div>
  );
}

export function ActivityPanel() {
  const items = useActivityStore((s) => s.items);
  const setItems = useActivityStore((s) => s.setItems);
  const [isCollapsed, setIsCollapsed] = useState(false);

  // 初始化模拟数据
  const handleLoadMockData = () => {
    setItems(mockActivities);
  };

  const activeCount = items.filter((i) => i.status === 'running').length;

  return (
    <div className="flex flex-col border-t border-border bg-surface">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-border">
        <button
          onClick={() => setIsCollapsed(!isCollapsed)}
          className="flex items-center gap-2 text-xs font-semibold text-text uppercase tracking-wide hover:text-primary transition-colors"
        >
          <ActivityIcon className="h-3.5 w-3.5" />
          活动
          {activeCount > 0 && (
            <span className="px-1.5 py-0.5 text-[10px] rounded-full bg-blue-500 text-white">
              {activeCount}
            </span>
          )}
        </button>
        {items.length === 0 && (
          <button
            onClick={handleLoadMockData}
            className="text-xs text-primary hover:text-primary-hover"
          >
            加载
          </button>
        )}
      </div>

      {/* Activity list */}
      {!isCollapsed && (
        <div className="max-h-48 overflow-y-auto">
          {items.length === 0 ? (
            <div className="px-3 py-4 text-xs text-muted text-center">暂无活动</div>
          ) : (
            <div className="py-1">
              {items.map((item) => (
                <ActivityRow key={item.id} item={item} />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
