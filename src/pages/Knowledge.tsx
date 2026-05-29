import { Upload } from 'lucide-react'
import { KnowledgeBrowser } from '../components/knowledge/KnowledgeBrowser'

export function Knowledge() {
  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      <div className="h-12 flex items-center justify-between px-5 border-b border-border bg-surface flex-shrink-0">
        <h2 className="text-[18px] font-semibold text-text">知识库</h2>
        <button className="flex items-center gap-1.5 px-3 py-1.5 bg-primary text-text-inverse text-xs rounded-radius-sm hover:bg-primary-hover transition-colors">
          <Upload className="w-3.5 h-3.5" />
          导入文档
        </button>
      </div>

      <div className="flex-1 overflow-y-auto">
        <KnowledgeBrowser />
      </div>
    </div>
  )
}
