import { Copy, ThumbsUp, ThumbsDown, BookOpen } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import type { Message as MessageType } from '../../lib/store'

interface MessageProps {
  message: MessageType
  onFeedback?: (messageId: string, feedback: 'up' | 'down') => void
  knowledgeRefs?: { id: string; title: string }[]
  attachments?: { name: string; size: number; type: string; dataUrl?: string }[]
}

export function Message({ message, onFeedback, knowledgeRefs, attachments }: MessageProps) {

  const isUser = message.role === 'user'
  const isAssistant = message.role === 'assistant'

  const copyToClipboard = () => {
    navigator.clipboard.writeText(message.content)
  }

  return (
    <div
      className={`flex gap-3 mb-5 max-w-[720px] ${isUser ? 'flex-row-reverse' : ''}`}
    >
      {/* 头像 */}
      <div
        className={`w-7 h-7 rounded-radius-sm flex-shrink-0 flex items-center justify-center text-xs font-semibold ${
          isAssistant
            ? 'bg-primary/10 text-primary'
            : 'bg-bg text-muted border border-border'
        }`}
      >
        {isAssistant ? 'S' : 'U'}
      </div>

      <div className={`flex-1 ${isUser ? 'flex flex-col items-end' : ''}`}>
        {/* Knowledge references */}
        {knowledgeRefs && knowledgeRefs.length > 0 && (
          <div className="flex flex-wrap gap-1 mb-1">
            {knowledgeRefs.map((ref) => (
              <span
                key={ref.id}
                className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[11px] bg-primary/10 text-primary"
              >
                <BookOpen className="w-2.5 h-2.5" />
                {ref.title}
              </span>
            ))}
          </div>
        )}

        {/* File attachments */}
        {attachments && attachments.length > 0 && (
          <div className="flex flex-wrap gap-1.5 mb-2">
            {attachments.map((file, idx) => (
              <span
                key={idx}
                className={`inline-flex items-center gap-1 px-2 py-1 rounded text-xs border ${
                  isUser
                    ? 'bg-text-inverse/15 border-text-inverse/20 text-text-inverse'
                    : 'bg-bg-subtle border-border text-text-secondary'
                }`}
              >
                {file.type.startsWith('image/') && file.dataUrl ? (
                  <img src={file.dataUrl} alt="" className="w-4 h-4 rounded object-cover" />
                ) : null}
                <span className="truncate max-w-24">{file.name}</span>
              </span>
            ))}
          </div>
        )}

        {/* 消息气泡 */}
        <div
          className={`px-3.5 py-2.5 rounded-radius-sm text-[13px] leading-relaxed ${
            isUser
              ? 'bg-primary text-text-inverse'
              : 'bg-surface border border-border'
          }`}
        >
          {/* Message content with Markdown */}
          {isAssistant ? (
            <div className="prose prose-sm max-w-none">
              <ReactMarkdown>{message.content}</ReactMarkdown>
            </div>
          ) : (
            <p className="whitespace-pre-wrap">{message.content}</p>
          )}
        </div>

        {/* 底部信息 */}
        <div className="flex items-center gap-2 mt-1 text-[11px] text-muted">
          {message.memory_applied && message.memory_applied > 0 && (
            <span className="text-primary">{message.memory_applied} 条记忆已应用</span>
          )}
          <span>{new Date(message.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
        </div>

        {/* Action buttons */}
        {onFeedback && (
          <div className="flex items-center gap-1 mt-2 pt-2 border-t border-border">
            <button onClick={copyToClipboard} className="p-1 rounded hover:bg-bg-hover" title="复制">
              <Copy className="w-4 h-4" />
            </button>
            <button onClick={() => onFeedback(message.id, 'up')} className="p-1 rounded hover:bg-bg-hover" title="有帮助">
              <ThumbsUp className="w-4 h-4" />
            </button>
            <button onClick={() => onFeedback(message.id, 'down')} className="p-1 rounded hover:bg-bg-hover" title="没帮助">
              <ThumbsDown className="w-4 h-4" />
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
