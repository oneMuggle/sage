/**
 * MemoryBrowser - 记忆浏览器组件
 * 显示记忆列表，支持筛选和统计
 */
import { useState, useEffect } from 'react'
import { memoryApi, Memory } from '../../lib/api'

type MemoryFilter = 'all' | 'fact' | 'preference' | 'project' | 'context'

interface MemoryBrowserProps {
  initialType?: MemoryFilter
}

const FILTER_LABELS: Record<MemoryFilter, string> = {
  all: '全部',
  fact: '事实',
  preference: '偏好',
  project: '项目',
  context: '上下文',
}

const TAG_CLASSES: Record<string, string> = {
  fact: 'bg-primary/10 text-primary',
  preference: 'bg-mem-subtle text-mem-accent',
  project: 'bg-warning/10 text-warning',
  context: 'bg-error/10 text-error',
}

export function MemoryBrowser({ initialType = 'all' }: MemoryBrowserProps) {
  const [memories, setMemories] = useState<Memory[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [filterType, setFilterType] = useState<MemoryFilter>(initialType)

  // 模拟统计数据
  const stats = {
    total: 247,
    thisWeek: 38,
    pending: 12,
    categories: 4,
  }

  // 加载记忆
  useEffect(() => {
    loadMemories()
  }, [filterType])

  const loadMemories = async () => {
    setLoading(true)
    setError(null)
    try {
      const type = filterType === 'all' ? undefined :
        filterType === 'fact' ? 'semantic' :
        filterType === 'preference' ? 'semantic' :
        filterType === 'project' ? 'episodic' :
        'episodic'
      const results = await memoryApi.getMemories(type, 1, 100)
      setMemories(results)
    } catch (err) {
      const message = err instanceof Error ? err.message : '加载失败'
      setError(message)
      setMemories([])
    } finally {
      setLoading(false)
    }
  }

  return (
    <div>
      {/* 统计卡片 */}
      <div className="flex gap-3 mb-5">
        <StatCard value={stats.total} label="总记忆数" />
        <StatCard value={stats.thisWeek} label="本周新增" />
        <StatCard value={stats.pending} label="待确认" />
        <StatCard value={stats.categories} label="记忆分类" />
      </div>

      {/* 筛选按钮 */}
      <div className="flex gap-1.5 mb-4">
        {Object.entries(FILTER_LABELS).map(([key, label]) => (
          <button
            key={key}
            className={`px-3 py-1 border border-border rounded-radius-sm text-xs cursor-pointer font-mono ${
              filterType === key
                ? 'bg-primary/10 text-primary border-primary'
                : 'bg-surface text-muted hover:text-text'
            }`}
            onClick={() => setFilterType(key as MemoryFilter)}
          >
            {label}
          </button>
        ))}
      </div>

      {/* 记忆列表 */}
      {loading ? (
        <div className="text-center text-muted py-12 text-sm">加载中...</div>
      ) : error ? (
        <div className="text-center py-12">
          <div className="text-sm text-error mb-2">{error}</div>
          <button
            onClick={loadMemories}
            className="px-3 py-1.5 text-xs border border-error rounded-radius-sm text-error hover:bg-error/5 transition-colors"
          >
            重试
          </button>
        </div>
      ) : memories.length === 0 ? (
        <div className="text-center text-muted py-12 text-sm">暂无记忆</div>
      ) : (
        <div className="flex flex-col gap-2">
          {memories.map((memory) => (
            <MemoryItemCard key={memory.id} memory={memory} />
          ))}
        </div>
      )}
    </div>
  )
}

function StatCard({ value, label }: { value: number; label: string }) {
  return (
    <div className="flex-1 p-3.5 border border-border rounded-radius-sm bg-surface">
      <div className="text-xl font-bold font-mono text-text">{value}</div>
      <div className="text-xs text-muted mt-1">{label}</div>
    </div>
  )
}

function MemoryItemCard({ memory }: { memory: Memory }) {
  const tags = memory.tags || []
  const primaryTag = tags[0] || 'fact'
  const tagLabel = FILTER_LABELS[primaryTag as MemoryFilter] || '事实'
  const tagClass = TAG_CLASSES[primaryTag] || TAG_CLASSES.fact

  // 从内容中提取标题（第一行或前30个字符）
  const content = memory.content || memory.summary || '无内容'
  const title = content.split('\n')[0].substring(0, 30)

  return (
    <div className="p-3 border border-border rounded-radius-sm bg-surface cursor-pointer hover:border-primary transition-colors">
      <div className="flex items-center justify-between mb-1">
        <span className="font-semibold text-sm text-text">
          {title}
        </span>
        <span className={`text-[11px] px-2 py-0.5 rounded font-mono ${tagClass}`}>
          {tagLabel}
        </span>
      </div>
      <div className="text-xs text-muted leading-relaxed">
        {content.length > 80 ? content.substring(0, 80) + '...' : content}
      </div>
      <div className="text-[11px] text-muted mt-1.5 font-mono">
        创建于 {formatDate(memory.created_at)} · 引用 {memory.access_count || 0} 次 · 置信度 {(memory.importance / 10).toFixed(2)}
      </div>
    </div>
  )
}

function formatDate(timestamp: number): string {
  const date = new Date(timestamp)
  return date.toLocaleDateString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  })
}
