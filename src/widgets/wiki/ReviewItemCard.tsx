// Review Item Card - 单个审核项卡片
import { AlertTriangle, Copy, FileQuestion, HelpCircle, Lightbulb } from 'lucide-react';

import type { ReviewItem } from '../../shared/types/wiki';

interface ReviewItemCardProps {
  item: ReviewItem;
  onAction?: (itemId: string, actionId: string) => void;
}

const TYPE_CONFIG = {
  contradiction: {
    icon: AlertTriangle,
    label: '矛盾',
    color: 'text-red-500',
    bgColor: 'bg-red-500/10',
  },
  duplicate: {
    icon: Copy,
    label: '重复',
    color: 'text-blue-500',
    bgColor: 'bg-blue-500/10',
  },
  'missing-page': {
    icon: FileQuestion,
    label: '缺页',
    color: 'text-purple-500',
    bgColor: 'bg-purple-500/10',
  },
  confirm: {
    icon: HelpCircle,
    label: '待确认',
    color: 'text-yellow-500',
    bgColor: 'bg-yellow-500/10',
  },
  suggestion: {
    icon: Lightbulb,
    label: '建议',
    color: 'text-green-500',
    bgColor: 'bg-green-500/10',
  },
};

export function ReviewItemCard({ item, onAction }: ReviewItemCardProps) {
  const config = TYPE_CONFIG[item.type];
  const Icon = config.icon;

  return (
    <div
      className={`rounded-lg border bg-surface p-4 transition-colors ${
        item.resolved ? 'border-border opacity-60' : 'border-border hover:border-primary/30'
      }`}
    >
      <div className="flex items-start gap-3">
        {/* Icon */}
        <div className={`flex h-8 w-8 items-center justify-center rounded-lg ${config.bgColor}`}>
          <Icon className={`h-4 w-4 ${config.color}`} />
        </div>

        {/* Content */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <span
              className={`text-xs font-medium px-2 py-0.5 rounded ${config.bgColor} ${config.color}`}
            >
              {config.label}
            </span>
            {item.resolved && <span className="text-xs text-muted">已解决</span>}
          </div>

          <h3 className="text-sm font-medium text-text mb-1">{item.title}</h3>
          <p className="text-xs text-text mb-2">{item.description}</p>

          {/* Affected pages */}
          <div className="flex flex-wrap gap-1 mb-3">
            {item.affectedPages.map((page) => (
              <span key={page} className="text-xs px-2 py-0.5 rounded bg-bg-muted text-muted">
                {page.split('/').pop()}
              </span>
            ))}
          </div>

          {/* Actions */}
          {!item.resolved && item.actions.length > 0 && (
            <div className="flex flex-wrap gap-2">
              {item.actions.map((action) => (
                <button
                  key={action.id}
                  onClick={() => onAction?.(item.id, action.id)}
                  className="px-3 py-1 text-xs rounded-radius-sm border border-border text-text hover:bg-bg-muted transition-colors"
                >
                  {action.label}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
