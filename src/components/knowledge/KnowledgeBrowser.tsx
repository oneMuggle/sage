import { clsx } from 'clsx'
import { Search } from 'lucide-react'

import { useKnowledge, type KnowledgeDoc } from '../../hooks/useKnowledge'

import { KnowledgeList } from './KnowledgeList'


interface KnowledgeBrowserProps {
  selectedIds?: Set<string>
  onToggle?: (id: string) => void
  onCardClick?: (doc: KnowledgeDoc) => void
}

export function KnowledgeBrowser({
  selectedIds,
  onToggle,
  onCardClick,
}: KnowledgeBrowserProps) {
  const {
    filteredDocs,
    searchQuery,
    setSearchQuery,
    selectedCategory,
    setSelectedCategory,
    categories,
    isLoading,
    error,
  } = useKnowledge()

  const internalSelected = selectedIds ?? new Set<string>()
  const internalToggle = onToggle ?? (() => {})

  return (
    <div className="p-5 space-y-4">
      <div className="flex items-center gap-3 px-3 py-2 border border-border rounded-radius-md bg-surface">
        <Search className="w-4 h-4 text-muted flex-shrink-0" />
        <input
          type="text"
          placeholder="搜索文档名称或内容…"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          className="flex-1 border-none bg-transparent outline-none text-sm text-text placeholder:text-muted"
        />
      </div>

      {isLoading ? (
        <div className="text-center text-muted py-12 text-sm">加载中...</div>
      ) : error ? (
        <div className="text-center py-12">
          <div className="text-sm text-error mb-2">{error}</div>
        </div>
      ) : (
        <>
          <div className="flex gap-2 flex-wrap">
            {categories.map((cat) => (
              <button
                key={cat}
                className={clsx(
                  'px-3 py-1 border rounded-radius-sm text-xs transition-colors',
                  selectedCategory === cat
                    ? 'bg-subtle text-primary border-primary'
                    : 'border-border bg-surface text-muted hover:text-text',
                )}
                onClick={() => setSelectedCategory(cat)}
              >
                {cat}
              </button>
            ))}
          </div>

          <KnowledgeList
            docs={filteredDocs}
            selectedIds={internalSelected}
            selectMode={false}
            onToggle={internalToggle}
            onCardClick={onCardClick}
          />
        </>
      )}
    </div>
  )
}
