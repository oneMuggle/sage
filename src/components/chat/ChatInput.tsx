import { useState, useRef } from 'react'
import { Send, Square, Image, Paperclip, BookOpen } from 'lucide-react'
import { Button } from '../common/Button'
import { useFileUpload } from '../../hooks/useFileUpload'
import { KnowledgeChip } from './KnowledgeChip'
import { FileAttachment } from './FileAttachment'

interface ChatInputProps {
  onSend: (message: string, options?: {
    knowledgeRefs?: { id: string; title: string }[]
    attachments?: { name: string; size: number; type: string; dataUrl?: string }[]
    images?: { name: string; size: number; type: string; dataUrl?: string }[]
  }) => void
  onInterrupt?: () => void
  isLoading?: boolean
  disabled?: boolean
  placeholder?: string
}

const KNOWLEDGE_DOCS = [
  { id: 'prd', title: '产品需求文档', desc: 'Sage 核心功能定义' },
  { id: 'api-docs', title: 'API 接口文档', desc: '内部 API 网关说明' },
  { id: 'deploy-guide', title: '部署指南', desc: 'Windows 环境部署步骤' },
  { id: 'memory-arch', title: '记忆系统架构', desc: '本地存储与同步策略' },
  { id: 'ui-spec', title: 'UI 设计规范', desc: '设计令牌与组件库' },
  { id: 'test-data', title: '测试数据集', desc: '样本对话和测试用例' },
]

export function ChatInput({
  onSend,
  onInterrupt,
  isLoading = false,
  disabled = false,
  placeholder = '输入消息...'
}: ChatInputProps) {
  const [value, setValue] = useState('')
  const [knowledgeRefs, setKnowledgeRefs] = useState<{ id: string; title: string }[]>([])
  const [showKnowledgeSelector, setShowKnowledgeSelector] = useState(false)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  const {
    files,
    images,
    addFile,
    addImage,
    removeFile,
    removeImage,
    clearAll,
    handleDrop,
    handleDragOver,
    isDragOver,
  } = useFileUpload()

  const handleSend = () => {
    if (!value.trim() || isLoading) return
    onSend(value.trim(), {
      knowledgeRefs: knowledgeRefs.length > 0 ? knowledgeRefs : undefined,
      attachments: files.length > 0 ? files : undefined,
      images: images.length > 0 ? images : undefined,
    })
    setValue('')
    setKnowledgeRefs([])
    clearAll()
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

  const handleImageSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const selectedFiles = e.target.files
    if (!selectedFiles) return
    Array.from(selectedFiles).forEach(addImage)
    e.target.value = ''
  }

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const selectedFiles = e.target.files
    if (!selectedFiles) return
    Array.from(selectedFiles).forEach(addFile)
    e.target.value = ''
  }

  const toggleKnowledgeRef = (doc: typeof KNOWLEDGE_DOCS[number]) => {
    setKnowledgeRefs((prev) =>
      prev.find((r) => r.id === doc.id)
        ? prev.filter((r) => r.id !== doc.id)
        : [...prev, { id: doc.id, title: doc.title }]
    )
  }

  const hasAttachments = files.length > 0 || images.length > 0 || knowledgeRefs.length > 0

  return (
    <div
      className="border-t p-4 bg-surface-elevated dark:bg-surface relative"
      onDrop={handleDrop}
      onDragOver={handleDragOver}
    >
      {isDragOver && (
        <div className="absolute inset-0 bg-primary/10 border-2 border-dashed border-primary rounded-lg flex items-center justify-center z-10">
          <p className="text-primary font-medium">拖放文件到此处</p>
        </div>
      )}

      {images.length > 0 && (
        <div className="flex gap-2 mb-2">
          {images.map((img, idx) => (
            <div key={idx} className="relative w-14 h-14 rounded-radius-sm border border-border overflow-hidden">
              {img.dataUrl && <img src={img.dataUrl} alt="" className="w-full h-full object-cover" />}
              <button
                className="absolute top-0.5 right-0.5 w-4 h-4 rounded-full bg-text/80 text-text-inverse flex items-center justify-center text-xs"
                onClick={() => removeImage(idx)}
              >
                ×
              </button>
            </div>
          ))}
        </div>
      )}

      {knowledgeRefs.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mb-2">
          {knowledgeRefs.map((ref, idx) => (
            <KnowledgeChip
              key={ref.id}
              title={ref.title}
              onRemove={() => setKnowledgeRefs((prev) => prev.filter((_, i) => i !== idx))}
            />
          ))}
        </div>
      )}

      {files.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mb-2">
          {files.map((file, idx) => (
            <FileAttachment
              key={idx}
              name={file.name}
              size={file.size}
              type={file.type}
              onRemove={() => removeFile(idx)}
            />
          ))}
        </div>
      )}

      <div className="flex items-end gap-2">
        <div className="flex gap-1">
          <Button
            variant="ghost"
            size="sm"
            title="插入图片"
            onClick={() => document.getElementById('chat-input-image')?.click()}
          >
            <Image className="w-4 h-4 text-muted" />
          </Button>
          <Button
            variant="ghost"
            size="sm"
            title="附加文件"
            onClick={() => document.getElementById('chat-input-file')?.click()}
          >
            <Paperclip className="w-4 h-4 text-muted" />
          </Button>
          <Button
            variant="ghost"
            size="sm"
            title="引用知识库"
            onClick={() => setShowKnowledgeSelector(!showKnowledgeSelector)}
          >
            <BookOpen className="w-4 h-4 text-muted" />
          </Button>
        </div>

        <div className="flex-1 relative">
          <textarea
            ref={textareaRef}
            value={value}
            onChange={handleInput}
            onKeyDown={handleKeyDown}
            placeholder={placeholder}
            disabled={disabled}
            rows={1}
            className="w-full resize-none rounded-lg border px-4 py-3 bg-bg-subtle border-border focus:outline-none focus:ring-2 focus:ring-primary/50 disabled:opacity-50 max-h-[200px]"
          />

          {showKnowledgeSelector && (
            <div className="absolute bottom-full left-0 mb-2 w-72 bg-surface-elevated border border-border rounded-radius-md shadow-lg z-20">
              <div className="p-3">
                <p className="text-xs font-medium text-text mb-2">引用知识库文档</p>
                {KNOWLEDGE_DOCS.map((doc) => {
                  const isSelected = !!knowledgeRefs.find((r) => r.id === doc.id)
                  return (
                    <button
                      key={doc.id}
                      className={`w-full text-left px-2 py-1.5 rounded text-xs flex items-center gap-2 transition-colors ${
                        isSelected
                          ? 'bg-subtle text-primary'
                          : 'hover:bg-bg-hover text-text-secondary'
                      }`}
                      onClick={() => toggleKnowledgeRef(doc)}
                    >
                      <span className={`w-3.5 h-3.5 rounded border flex items-center justify-center flex-shrink-0 ${
                        isSelected ? 'bg-primary border-primary' : 'border-border'
                      }`}>
                        {isSelected && (
                          <svg width="8" height="8" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="4">
                            <polyline points="20 6 9 17 4 12" />
                          </svg>
                        )}
                      </span>
                      <div>
                        <div className="font-medium">{doc.title}</div>
                        <div className="text-muted">{doc.desc}</div>
                      </div>
                    </button>
                  )
                })}
              </div>
            </div>
          )}
        </div>

        {isLoading ? (
          <Button variant="danger" onClick={onInterrupt} title="停止">
            <Square className="w-5 h-5" />
          </Button>
        ) : (
          <Button
            variant="primary"
            onClick={handleSend}
            disabled={!value.trim() && !hasAttachments || disabled}
          >
            <Send className="w-5 h-5" />
          </Button>
        )}
      </div>

      <input type="file" id="chat-input-image" accept="image/*" multiple className="hidden" onChange={handleImageSelect} />
      <input type="file" id="chat-input-file" multiple className="hidden" onChange={handleFileSelect} />

      <p className="text-xs text-muted text-center mt-2">
        支持拖放文件到输入区域 · 文件将作为上下文发送给 AI
      </p>
    </div>
  )
}
