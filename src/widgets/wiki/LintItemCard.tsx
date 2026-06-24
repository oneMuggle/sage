// Lint Item Card - 单个 Lint 检查项卡片
import { AlertCircle, AlertTriangle, Info, Link2, Unlink } from 'lucide-react';

import type { LintItem } from '../../shared/types/wiki';

interface LintItemCardProps {
  item: LintItem;
  onFix?: (id: string) => void;
  onDismiss?: (id: string) => void;
}

const TYPE_CONFIG = {
  orphan: {
    icon: Unlink,
    label: '孤儿页',
    color: 'text-orange-500',
    bgColor: 'bg-orange-500/10',
  },
  'broken-link': {
    icon: Link2,
    label: '断链',
    color: 'text-red-500',
    bgColor: 'bg-red-500/10',
  },
  'no-outlinks': {
    icon: AlertCircle,
    label: '无出链',
    color: 'text-yellow-500',
    bgColor: 'bg-yellow-500/10',
  },
  semantic: {
    icon: Info,
    label: '语义问题',
    color: 'text-blue-500',
    bgColor: 'bg-blue-500/10',
  },
};

export function LintItemCard({ item, onFix, onDismiss }: LintItemCardProps) {
  const config = TYPE_CONFIG[item.type];
  const Icon = config.icon;

  return (
    <div className="rounded-lg border border-border bg-surface p-4 hover:border-primary/30 transition-colors">
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
            <span className="text-xs text-muted">
              {item.severity === 'warning' ? (
                <AlertTriangle className="inline h-3 w-3 mr-0.5" />
              ) : (
                <Info className="inline h-3 w-3 mr-0.5" />
              )}
              {item.severity}
            </span>
          </div>

          <p className="text-sm text-text mb-1">{item.message}</p>
          <p className="text-xs text-muted truncate">{item.page}</p>

          {item.suggestion && (
            <p className="text-xs text-muted mt-2 italic">建议: {item.suggestion}</p>
          )}
        </div>

        {/* Actions */}
        <div className="flex flex-col gap-1">
          {onFix && (
            <button
              onClick={() => onFix(item.id)}
              className="px-2 py-1 text-xs rounded-radius-sm border border-border text-text hover:bg-bg-muted transition-colors"
            >
              修复
            </button>
          )}
          {onDismiss && (
            <button
              onClick={() => onDismiss(item.id)}
              className="px-2 py-1 text-xs rounded-radius-sm border border-border text-muted hover:bg-bg-muted transition-colors"
            >
              忽略
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
