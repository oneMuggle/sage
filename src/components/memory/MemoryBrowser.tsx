/**
 * MemoryBrowser - 记忆浏览器组件
 * 显示记忆列表，支持筛选和搜索
 */
import { useState, useEffect } from 'react'
import { memoryApi, Memory } from '../../lib/api'
import { MemoryItem } from './MemoryItem'

interface MemoryBrowserProps {
  initialType?: 'episodic' | 'semantic' | 'all'
}

export function MemoryBrowser({ initialType = 'all' }: MemoryBrowserProps) {
  const [memories, setMemories] = useState<Memory[]>([])
  const [loading, setLoading] = useState(true)
  const [searchQuery, setSearchQuery] = useState('')
  const [filterType, setFilterType] = useState<'episodic' | 'semantic' | 'all'>(initialType)
  const [currentPage, setCurrentPage] = useState(1)
  const pageSize = 20

  // 加载记忆
  useEffect(() => {
    loadMemories()
  }, [filterType, currentPage])

  const loadMemories = async () => {
    setLoading(true)
    try {
      if (searchQuery) {
        const results = await memoryApi.searchMemories(searchQuery, filterType === 'all' ? undefined : filterType)
        setMemories(results)
      } else {
        const type = filterType === 'all' ? undefined : filterType
        const results = await memoryApi.getMemories(type, currentPage, pageSize)
        setMemories(results)
      }
    } catch (error) {
      console.error('加载记忆失败:', error)
    } finally {
      setLoading(false)
    }
  }

  // 搜索处理
  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault()
    setCurrentPage(1)
    loadMemories()
  }

  // 删除记忆
  const handleDelete = async (id: string) => {
    try {
      await memoryApi.deleteMemory(id)
      setMemories(memories.filter(m => m.id !== id))
    } catch (error) {
      console.error('删除记忆失败:', error)
    }
  }

  // 筛选类型变化
  const handleTypeChange = (type: 'episodic' | 'semantic' | 'all') => {
    setFilterType(type)
    setCurrentPage(1)
  }

  return (
    <div className="memory-browser">
      {/* 搜索栏 */}
      <form onSubmit={handleSearch} className="memory-search">
        <input
          type="text"
          placeholder="搜索记忆..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          className="memory-search-input"
        />
        <button type="submit" className="memory-search-btn">搜索</button>
      </form>

      {/* 筛选标签 */}
      <div className="memory-filters">
        <button
          className={`filter-tag ${filterType === 'all' ? 'active' : ''}`}
          onClick={() => handleTypeChange('all')}
        >
          全部
        </button>
        <button
          className={`filter-tag ${filterType === 'episodic' ? 'active' : ''}`}
          onClick={() => handleTypeChange('episodic')}
        >
          情景记忆
        </button>
        <button
          className={`filter-tag ${filterType === 'semantic' ? 'active' : ''}`}
          onClick={() => handleTypeChange('semantic')}
        >
          语义记忆
        </button>
      </div>

      {/* 记忆列表 */}
      <div className="memory-list">
        {loading ? (
          <div className="memory-loading">加载中...</div>
        ) : memories.length === 0 ? (
          <div className="memory-empty">暂无记忆</div>
        ) : (
          memories.map((memory) => (
            <MemoryItem
              key={memory.id}
              memory={memory}
              onDelete={handleDelete}
            />
          ))
        )}
      </div>

      {/* 分页 */}
      {memories.length > 0 && (
        <div className="memory-pagination">
          <button
            onClick={() => setCurrentPage(p => Math.max(1, p - 1))}
            disabled={currentPage === 1}
          >
            上一页
          </button>
          <span>第 {currentPage} 页</span>
          <button
            onClick={() => setCurrentPage(p => p + 1)}
            disabled={memories.length < pageSize}
          >
            下一页
          </button>
        </div>
      )}
    </div>
  )
}
