import { clsx } from 'clsx';
import { BookOpen } from 'lucide-react';

import type { KnowledgeDoc } from '../../shared/lib/hooks/useKnowledge';

interface KnowledgeCardProps {
  doc: KnowledgeDoc;
  isSelected: boolean;
  selectMode: boolean;
  onClick: () => void;
  onToggle: () => void;
}

export function KnowledgeCard({
  doc,
  isSelected,
  selectMode,
  onClick,
  onToggle,
}: KnowledgeCardProps) {
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      if (selectMode) {
        onToggle();
      } else {
        onClick();
      }
    }
  };

  return (
    <div
      role="button"
      tabIndex={0}
      aria-label={`${selectMode ? '选择' : '打开'}知识库文档 ${doc.title}`}
      aria-pressed={isSelected}
      onClick={selectMode ? onToggle : onClick}
      onKeyDown={handleKeyDown}
      className={clsx(
        'border rounded-radius-md p-space-4 cursor-pointer transition-all',
        'hover:border-primary focus:outline-none focus:ring-2 focus:ring-primary',
        isSelected ? 'border-primary bg-active' : 'border-border bg-surface',
      )}
    >
      {selectMode && (
        <div className="flex justify-end mb-2">
          <button
            className={clsx(
              'w-5 h-5 rounded-radius-sm border-2 flex items-center justify-center transition-all',
              isSelected ? 'bg-primary border-primary' : 'border-border bg-surface',
            )}
            onClick={(e) => {
              e.stopPropagation();
              onToggle();
            }}
          >
            {isSelected && (
              <svg
                width="12"
                height="12"
                viewBox="0 0 24 24"
                fill="none"
                stroke="white"
                strokeWidth="3"
              >
                <polyline points="20 6 9 17 4 12" />
              </svg>
            )}
          </button>
        </div>
      )}

      <div className="flex items-start gap-3">
        <div
          className={clsx(
            'w-8 h-8 rounded-radius-sm flex items-center justify-center flex-shrink-0',
            isSelected ? 'bg-primary text-text-inverse' : 'bg-subtle text-primary',
          )}
        >
          <BookOpen className="w-4 h-4" />
        </div>
        <div className="min-w-0 flex-1">
          <h3 className="font-semibold text-sm text-text mb-1 truncate">{doc.title}</h3>
          <p className="text-xs text-muted mb-2 line-clamp-2">{doc.description}</p>
          <div className="flex items-center gap-2 text-xs text-muted">
            <span className="bg-subtle px-2 py-0.5 rounded-radius-sm text-text-secondary">
              {doc.category}
            </span>
            <span>{doc.pages} 页</span>
            <span className="text-muted">·</span>
            <span>{formatDate(doc.updated_at)}</span>
          </div>
        </div>
      </div>
    </div>
  );
}

function formatDate(dateStr: string): string {
  const date = new Date(dateStr);
  const now = new Date();
  const diff = now.getTime() - date.getTime();
  const days = Math.floor(diff / (1000 * 60 * 60 * 24));

  if (days === 0) return '今天';
  if (days === 1) return '昨天';
  if (days < 7) return `${days} 天前`;
  return dateStr;
}
