import { useState } from 'react'
import { Copy, ThumbsUp, ThumbsDown } from 'lucide-react'
import type { Message as MessageType } from '../../lib/store'

interface MessageProps {
  message: MessageType
  onFeedback?: (messageId: string, feedback: 'up' | 'down') => void
}

export function Message({ message, onFeedback }: MessageProps) {
  const [showActions, setShowActions] = useState(false)

  const isUser = message.role === 'user'
  const isAssistant = message.role === 'assistant'

  const copyToClipboard = () => {
    navigator.clipboard.writeText(message.content)
  }

  return (
    <div
      className={`flex ${isUser ? 'justify-end' : 'justify-start'} mb-4`}
      onMouseEnter={() => setShowActions(true)}
      onMouseLeave={() => setShowActions(false)}
    >
      <div
        className={`
          max-w-[80%] rounded-2xl px-4 py-3
          ${isUser
            ? 'bg-primary text-white rounded-br-md'
            : 'bg-gray-100 dark:bg-gray-700 rounded-bl-md'
          }
        `}
      >
        {/* 消息内容 */}
        <div className="prose prose-sm dark:prose-invert max-w-none">
          <p className="whitespace-pre-wrap">{message.content}</p>
        </div>

        {/* 工具调用显示 */}
        {message.tool_calls && message.tool_calls.length > 0 && (
          <div className="mt-2 text-xs opacity-75">
            使用工具: {message.tool_calls.map(tc => tc.name).join(', ')}
          </div>
        )}

        {/* 底部信息 */}
        <div className={`
          flex items-center gap-2 mt-1 text-xs
          ${isUser ? 'text-white/70' : 'text-gray-500 dark:text-gray-400'}
        `}>
          <span>{new Date(message.created_at).toLocaleTimeString()}</span>
        </div>

        {/* 操作按钮 */}
        {showActions && isAssistant && (
          <div className={`
            flex items-center gap-1 mt-2 pt-2 border-t
            ${isUser ? 'border-white/20' : 'border-gray-200 dark:border-gray-600'}
          `}>
            <button
              onClick={copyToClipboard}
              className="p-1 rounded hover:bg-black/10 dark:hover:bg-white/10"
              title="复制"
            >
              <Copy className="w-4 h-4" />
            </button>

            {onFeedback && (
              <>
                <button
                  onClick={() => onFeedback(message.id, 'up')}
                  className="p-1 rounded hover:bg-black/10"
                  title="有帮助"
                >
                  <ThumbsUp className="w-4 h-4" />
                </button>
                <button
                  onClick={() => onFeedback(message.id, 'down')}
                  className="p-1 rounded hover:bg-black/10"
                  title="没帮助"
                >
                  <ThumbsDown className="w-4 h-4" />
                </button>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
