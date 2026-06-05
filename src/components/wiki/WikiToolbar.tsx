// Wiki Toolbar - top navigation and actions
import { FileText, Search, MessageSquare } from 'lucide-react'

import { useWikiStore } from '../../stores/wiki-store'
import type { WikiView } from '../../types/wiki'

export function WikiToolbar() {
  const project = useWikiStore((s) => s.project)
  const activeView = useWikiStore((s) => s.activeView)
  const setActiveView = useWikiStore((s) => s.setActiveView)
  const selectedFile = useWikiStore((s) => s.selectedFile)

  if (!project) return null

  const views: { key: WikiView; label: string; icon: React.ReactNode }[] = [
    { key: 'browser', label: '浏览', icon: <FileText className="h-4 w-4" /> },
    { key: 'search', label: '搜索', icon: <Search className="h-4 w-4" /> },
    { key: 'chat', label: '对话', icon: <MessageSquare className="h-4 w-4" /> },
  ]

  return (
    <div className="flex items-center justify-between border-b border-border px-4 py-2 bg-surface">
      <div className="flex items-center gap-1">
        <span className="text-sm font-semibold text-text mr-3">{project.name}</span>
        {views.map((view) => (
          <button
            key={view.key}
            onClick={() => setActiveView(view.key)}
            className={`flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-radius-sm transition-colors ${
              activeView === view.key
                ? 'bg-primary/10 text-primary'
                : 'text-muted hover:text-text hover:bg-bg-muted'
            }`}
          >
            {view.icon}
            {view.label}
          </button>
        ))}
      </div>
      {selectedFile && (
        <span className="text-xs text-muted truncate max-w-[200px]">
          {selectedFile.split('/').pop()}
        </span>
      )}
    </div>
  )
}
