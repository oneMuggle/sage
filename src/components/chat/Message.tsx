import { useState } from 'react'
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
            ? 'bg-primary text-text-inverse rounded-br-md'
            : 'bg-bg-muted rounded-bl-md border border-border'
          }
        `}
      >
        {/* Knowledge references */}
        {knowledgeRefs && knowledgeRefs.length > 0 && (
          <div className="flex flex-wrap gap-1 mb-2">
            {knowledgeRefs.map((ref) => (
              <span
                key={ref.id}
                className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-xs ${
                  isUser
                    ? 'bg-text-inverse/20 text-text-inverse'
                    : 'bg-subtle text-primary'
                }`}
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

        {/* Message content with Markdown */}
        <div className="text-sm leading-relaxed">
          {isAssistant ? (
            <div className={`prose prose-sm max-w-none ${isUser ? 'prose-invert' : ''}`}>
              <ReactMarkdown>{message.content}</ReactMarkdown>
            </div>
          ) : (
            <p className="whitespace-pre-wrap">{message.content}</p>
          )}
        </div>

        {/* Tool calls display */}
        {message.tool_calls && message.tool_calls.length > 0 && (
          <div className="mt-2 text-xs opacity-75">
            使用工具: {message.tool_calls.map((tc) => tc.name).join(', ')}
          </div>
        )}

        {/* Bottom info */}
        <div
          className={`
            flex items-center gap-2 mt-2 text-xs
            ${isUser ? 'text-text-inverse/70' : 'text-muted'}
          `}
        >
          <span>{new Date(message.created_at).toLocaleTimeString()}</span>
        </div>

        {/* Action buttons */}
        {showActions && isAssistant && (
          <div
            className={`
              flex items-center gap-1 mt-2 pt-2 border-t
              ${isUser ? 'border-text-inverse/20' : 'border-border'}
            `}
          >
            <button
              onClick={copyToClipboard}
              className="p-1 rounded hover:bg-text/10"
              title="复制"
            >
              <Copy className="w-4 h-4" />
            </button>

            {onFeedback && (
              <>
                <button
                  onClick={() => onFeedback(message.id, 'up')}
                  className="p-1 rounded hover:bg-text/10"
                  title="有帮助"
                >
                  <ThumbsUp className="w-4 h-4" />
                </button>
                <button
                  onClick={() => onFeedback(message.id, 'down')}
                  className="p-1 rounded hover:bg-text/10"
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
