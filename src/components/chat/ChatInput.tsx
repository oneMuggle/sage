import { useState, useRef } from 'react'
import { Send, Square } from 'lucide-react'
import { Button } from '../common/Button'

interface ChatInputProps {
  onSend: (message: string) => void
  onInterrupt?: () => void
  isLoading?: boolean
  disabled?: boolean
  placeholder?: string
}

export function ChatInput({
  onSend,
  onInterrupt,
  isLoading = false,
  disabled = false,
  placeholder = '输入消息...'
}: ChatInputProps) {
  const [value, setValue] = useState('')
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  const handleSend = () => {
    if (!value.trim() || isLoading) return
    onSend(value.trim())
    setValue('')
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const handleInput = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setValue(e.target.value)
    const ta = e.target
    ta.style.height = 'auto'
    ta.style.height = `${Math.min(ta.scrollHeight, 200)}px`
  }

  return (
    <div className="flex items-end gap-2 border-t p-4 bg-white dark:bg-gray-800">
      {/* 功能按钮 */}
      <div className="flex gap-1">
        <Button variant="ghost" size="sm" title="记忆">
          💭
        </Button>
        <Button variant="ghost" size="sm" title="技能">
          ⚡
        </Button>
        <Button variant="ghost" size="sm" title="设置">
          ⚙️
        </Button>
      </div>

      {/* 输入框 */}
      <div className="flex-1 relative">
        <textarea
          ref={textareaRef}
          value={value}
          onChange={handleInput}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          disabled={disabled}
          rows={1}
          className={`
            w-full resize-none rounded-lg border px-4 py-3
            bg-gray-50 dark:bg-gray-700
            border-gray-200 dark:border-gray-600
            focus:outline-none focus:ring-2 focus:ring-primary/50
            disabled:opacity-50
            max-h-[200px]
          `}
        />
      </div>

      {/* 发送按钮 */}
      {isLoading ? (
        <Button variant="danger" onClick={onInterrupt} title="停止">
          <Square className="w-5 h-5" />
        </Button>
      ) : (
        <Button
          variant="primary"
          onClick={handleSend}
          disabled={!value.trim() || disabled}
        >
          <Send className="w-5 h-5" />
        </Button>
      )}
    </div>
  )
}
