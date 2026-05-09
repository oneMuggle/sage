/**
 * MemoryItem - 单条记忆显示组件
 * 显示记忆内容、重要性星级、标签和删除按钮
 */
import { Memory } from '../../lib/api'

interface MemoryItemProps {
  memory: Memory
  onDelete: (id: string) => void
}

// 重要性星级显示
function ImportanceStars({ importance }: { importance: number }) {
  const stars = Math.min(10, Math.max(1, importance || 5))
  return (
    <div className="importance-stars">
      {Array.from({ length: 5 }, (_, i) => (
        <span
          key={i}
          className={`star ${i < Math.ceil(stars / 2) ? 'filled' : ''}`}
        >
          ★
        </span>
      ))}
      <span className="importance-value">({stars}/10)</span>
    </div>
  )
}

// 格式化时间戳
function formatTime(timestamp: number): string {
  const date = new Date(timestamp)
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  })
}

export function MemoryItem({ memory, onDelete }: MemoryItemProps) {
  const handleDelete = () => {
    if (confirm('确定要删除这条记忆吗？')) {
      onDelete(memory.id)
    }
  }

  const tags = memory.tags || []
  const memoryType = memory.memory_type || 'episodic'

  return (
    <div className={`memory-item memory-item-${memoryType}`}>
      {/* 记忆类型标签 */}
      <div className="memory-type-badge">
        {memoryType === 'episodic' ? '情景' : '语义'}
      </div>

      {/* 记忆内容 */}
      <div className="memory-content">
        <p>{memory.content || memory.summary || '无内容'}</p>
      </div>

      {/* 记忆元信息 */}
      <div className="memory-meta">
        {/* 重要性 */}
        <div className="memory-importance">
          <ImportanceStars importance={memory.importance || 5} />
        </div>

        {/* 标签 */}
        {tags.length > 0 && (
          <div className="memory-tags">
            {tags.map((tag: string, index: number) => (
              <span key={index} className="memory-tag">
                {tag}
              </span>
            ))}
          </div>
        )}

        {/* 时间 */}
        <div className="memory-time">
          {formatTime(memory.created_at)}
        </div>
      </div>

      {/* 删除按钮 */}
      <button
        className="memory-delete-btn"
        onClick={handleDelete}
        title="删除记忆"
      >
        ×
      </button>
    </div>
  )
}
