import { BookOpen, X } from 'lucide-react'

interface KnowledgeChipProps {
  title: string
  onRemove?: () => void
}

export function KnowledgeChip({ title, onRemove }: KnowledgeChipProps) {
  return (
    <span className="inline-flex items-center gap-1 px-2 py-1 rounded-radius-sm bg-subtle text-xs text-text-secondary border border-border">
      <BookOpen className="w-3 h-3" />
      <span className="truncate max-w-32">{title}</span>
      {onRemove && (
        <button
          className="ml-1 hover:text-text transition-colors"
          onClick={onRemove}
        >
          <X className="w-3 h-3" />
        </button>
      )}
    </span>
  )
}
