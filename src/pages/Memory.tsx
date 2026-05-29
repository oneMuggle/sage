import { Plus, Download } from 'lucide-react'
import { MemoryBrowser } from '../components/memory'

export function Memory() {
  return (
    <div className="flex-1 overflow-y-auto p-5">
      <div className="flex items-center justify-between mb-5">
        <h2 className="text-[18px] font-semibold text-text">记忆库</h2>
        <div className="flex gap-2">
          <button className="flex items-center gap-1.5 px-3 py-1.5 bg-primary text-text-inverse text-xs rounded-radius-sm hover:bg-primary-hover transition-colors">
            <Plus className="w-3.5 h-3.5" />
            新建记忆
          </button>
          <button className="flex items-center gap-1.5 px-3 py-1.5 border border-border text-xs rounded-radius-sm bg-surface text-text-secondary hover:text-text transition-colors">
            <Download className="w-3.5 h-3.5" />
            导出
          </button>
        </div>
      </div>

      <MemoryBrowser initialType="all" />
    </div>
  )
}
