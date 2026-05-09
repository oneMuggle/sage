/**
 * Memory Page - 记忆管理页面
 * 路由: /memory
 */
import { MemoryBrowser } from '../components/memory'

export function Memory() {
  return (
    <div className="memory-page">
      <div className="memory-page-header">
        <h1>记忆库</h1>
        <p className="memory-page-subtitle">
          管理你的情景记忆和语义知识
        </p>
      </div>

      <MemoryBrowser initialType="all" />
    </div>
  )
}
