/**
 * MemoryBrowser - 记忆浏览器组件
 * 显示记忆列表，支持筛选和统计
 */
import { useState, useEffect } from 'react'

import { memoryApi, Memory } from '../../lib/api'

type MemoryFilter = 'all' | 'episodic' | 'semantic'

interface MemoryBrowserProps {
  initialType?: MemoryFilter
  onNewMemory?: () => void
}

const FILTER_LABELS: Record<MemoryFilter, string> = {
  all: '全部',
  episodic: '情景记忆',
  semantic: '语义记忆',
}

const TAG_CLASSES: Record<string, string> = {
  episodic: 'bg-primary/10 text-primary',
  semantic: 'bg-warning/10 text-warning',
}

export function MemoryBrowser({ initialType = 'all' }: MemoryBrowserProps) {
  const [memories, setMemories] = useState<Memory[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [filterType, setFilterType] = useState<MemoryFilter>(initialType)
  const [stats, setStats] = useState({ total: 0, thisWeek: 0, episodic: 0, semantic: 0 })

  // 加载记忆
  useEffect(() => {
    loadMemories()
    loadStats()
  }, [filterType])

  const loadStats = async () => {
    try {
      const [episodic, semantic] = await Promise.all([
        memoryApi.getMemories('episodic', 1, 1),
        memoryApi.getMemories('semantic', 1, 1),
      ])
      // We can't get exact counts without a stats endpoint, but we can estimate
      // For now, show the actual loaded counts
      setStats({
        total: memories.length,
        thisWeek: memories.filter(m => Date.now() - m.created_at < 7 * 24 * 60 * 60 * 1000).length,
        episodic: episodic.length,
        semantic: semantic.length,
      })
    } catch {
      // Stats unavailable
    }
  }

  const loadMemories = async () => {
    setLoading(true)
    setError(null)
    try {
      const type = filterType === 'all' ? undefined : filterType
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
        <StatCard value={stats.total} label="当前显示" />
        <StatCard value={stats.thisWeek} label="本周新增" />
        <StatCard value={stats.episodic} label="情景记忆" />
        <StatCard value={stats.semantic} label="语义记忆" />
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
  const primaryTag = tags[0] || (memory.memory_type || 'episodic')
  const tagLabel = FILTER_LABELS[primaryTag as MemoryFilter] || primaryTag
  const tagClass = TAG_CLASSES[primaryTag] || TAG_CLASSES.episodic

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
