import { Link, useLocation } from 'react-router-dom'
import { MessageSquare, Settings, Brain, Zap, Users, BookOpen } from 'lucide-react'
import { clsx } from 'clsx'

// 导航项配置
const navItems = [
  { path: '/chat', label: '对话', icon: MessageSquare },
  { path: '/memory', label: '记忆', icon: Brain },
  { path: '/knowledge', label: '知识库', icon: BookOpen },
  { path: '/agents', label: 'Agent', icon: Users },
  { path: '/skills', label: '技能', icon: Zap },
  { path: '/settings', label: '设置', icon: Settings },
]

export function Sidebar() {
  const location = useLocation()

  return (
    <aside className="w-64 h-screen bg-bg-muted border-r border-border flex flex-col">
      {/* Logo 区域 */}
      <div className="h-16 flex items-center px-6 border-b border-border">
        <h1 className="text-xl font-bold text-primary">Sage</h1>
        <span className="ml-2 text-xs text-muted">记忆型 AI 助手</span>
      </div>

      {/* 导航列表 */}
      <nav className="flex-1 py-4">
        {navItems.map((item) => {
          const isActive = location.pathname === item.path || 
            (item.path === '/chat' && location.pathname === '/')
          const Icon = item.icon
          
          return (
            <Link
              key={item.path}
              to={item.path}
              className={clsx(
                'flex items-center gap-3 px-6 py-3 mx-2 rounded-lg transition-colors',
                isActive
                  ? 'bg-primary text-text-inverse'
                  : 'text-text-secondary hover:bg-bg-hover'
              )}
            >
              <Icon className="w-5 h-5" />
              <span className="font-medium">{item.label}</span>
            </Link>
          )
        })}
      </nav>

      {/* 底部信息 */}
      <div className="p-4 border-t border-border">
        <p className="text-xs text-muted text-center">
          v0.1.0 · Windows 7+
        </p>
      </div>
    </aside>
  )
}
