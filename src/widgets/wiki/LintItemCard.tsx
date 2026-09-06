// Lint Item Card - 单个 Lint 检查项卡片
import {
  AlertCircle,
  AlertTriangle,
  FileWarning,
  FileX2,
  FolderX,
  Info,
  Link2,
  ListMinus,
  Unlink,
} from 'lucide-react';

import type { LintItem } from '../../shared/types/wiki';

interface LintItemCardProps {
  item: LintItem;
  onFix?: (id: string) => void;
  onDismiss?: (id: string) => void;
}

interface TypeConfig {
  icon: React.ElementType;
  label: string;
  color: string;
  bgColor: string;
}

const TYPE_CONFIG: Record<string, TypeConfig> = {
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
    icon: ListMinus,
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
  // --- Backend-backed lint types ---
  required_dir: {
    icon: FolderX,
    label: '必需目录缺失',
    color: 'text-red-500',
    bgColor: 'bg-red-500/10',
  },
  required_file: {
    icon: FileX2,
    label: '必需文件缺失',
    color: 'text-red-500',
    bgColor: 'bg-red-500/10',
  },
  frontmatter_missing: {
    icon: FileWarning,
    label: '缺少 frontmatter',
    color: 'text-amber-500',
    bgColor: 'bg-amber-500/10',
  },
  frontmatter_title: {
    icon: FileWarning,
    label: '缺少 title 字段',
    color: 'text-amber-500',
    bgColor: 'bg-amber-500/10',
  },
  wikilink_broken: {
    icon: Link2,
    label: '断链',
    color: 'text-red-500',
    bgColor: 'bg-red-500/10',
  },
};

const FALLBACK_CONFIG: TypeConfig = {
  icon: AlertCircle,
  label: '其他',
  color: 'text-muted',
  bgColor: 'bg-bg-muted',
};

const SEVERITY_ICON: Record<string, React.ElementType> = {
  error: AlertTriangle,
  warning: AlertTriangle,
  info: Info,
};

const SEVERITY_COLOR: Record<string, string> = {
  error: 'text-red-500',
  warning: 'text-amber-500',
  info: 'text-blue-500',
};

export function LintItemCard({ item, onFix, onDismiss }: LintItemCardProps) {
  const config = TYPE_CONFIG[item.type] ?? FALLBACK_CONFIG;
  const Icon = config.icon;
  const SeverityIcon = SEVERITY_ICON[item.severity] ?? Info;
  const severityColor = SEVERITY_COLOR[item.severity] ?? 'text-muted';

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
            <span className={`text-xs ${severityColor}`}>
              <SeverityIcon className="inline h-3 w-3 mr-0.5" />
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
