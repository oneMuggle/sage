import { Send, Square, Image, Paperclip, BookOpen, Clock } from 'lucide-react';
import { useState, useRef } from 'react';

import { AtFileMenu, useAtFileQuery, useBtwCommand } from '../../features/chat';
import { useFileUpload } from '../../shared/lib/hooks/useFileUpload';

import { FileAttachment } from './FileAttachment';
import { KnowledgeChip } from './KnowledgeChip';

interface ChatInputProps {
  onSend: (
    message: string,
    options?: {
      knowledgeRefs?: { id: string; title: string }[];
      attachments?: { name: string; size: number; type: string; dataUrl?: string }[];
      images?: { name: string; size: number; type: string; dataUrl?: string }[];
    },
  ) => void;
  onInterrupt?: () => void;
  onSchedule?: () => void;
  isLoading?: boolean;
  disabled?: boolean;
  placeholder?: string;
}

const KNOWLEDGE_DOCS = [
  { id: 'prd', title: '产品需求文档', desc: 'Sage 核心功能定义' },
  { id: 'api-docs', title: 'API 接口文档', desc: '内部 API 网关说明' },
  { id: 'deploy-guide', title: '部署指南', desc: 'Windows 环境部署步骤' },
  { id: 'memory-arch', title: '记忆系统架构', desc: '本地存储与同步策略' },
  { id: 'ui-spec', title: 'UI 设计规范', desc: '设计令牌与组件库' },
];

export function ChatInput({
  onSend,
  onInterrupt,
  onSchedule,
  isLoading = false,
  disabled = false,
  placeholder = '输入消息...',
}: ChatInputProps) {
  const [value, setValue] = useState('');
  const [cursorPos, setCursorPos] = useState(0);
  const [knowledgeRefs, setKnowledgeRefs] = useState<{ id: string; title: string }[]>([]);
  const [showKnowledgeSelector, setShowKnowledgeSelector] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Phase 6 (M8 /btw): @文件提及 + /btw 补充消息
  const btw = useBtwCommand();
  const atQuery = useAtFileQuery(value, cursorPos);

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
  } = useFileUpload();

  const handleSend = () => {
    if (!value.trim() || disabled) return;
    onSend(value, {
      knowledgeRefs: knowledgeRefs.length > 0 ? knowledgeRefs : undefined,
      attachments: files.length > 0 ? files : undefined,
      images: images.length > 0 ? images : undefined,
    });
    setValue('');
    setKnowledgeRefs([]);
    clearAll();
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleInput = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const newValue = e.target.value;
    setValue(newValue);
    setCursorPos(e.target.selectionStart ?? newValue.length);
    const ta = e.target;
    ta.style.height = 'auto';
    ta.style.height = `${Math.min(ta.scrollHeight, 200)}px`;

    // Phase 6 (M8 /btw): /btw 拦截
    const btwMatch = newValue.match(/^\/btw\s+(.+)$/);
    if (btwMatch) {
      btw.open(btwMatch[1]);
      setValue('');
      return;
    }
  };

  const handleImageSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const selectedFiles = e.target.files;
    if (!selectedFiles) return;
    Array.from(selectedFiles).forEach((file) => {
      if (file.type.startsWith('image/')) {
        addImage(file);
      } else {
        addFile(file);
      }
    });
  };

  const toggleKnowledge = (id: string, title: string) => {
    setKnowledgeRefs((prev) => {
      const exists = prev.find((k) => k.id === id);
      if (exists) return prev.filter((k) => k.id !== id);
      return [...prev, { id, title }];
    });
  };

  return (
    <div
      className={`border-t border-border p-4 ${isDragOver ? 'bg-bg-hover' : ''}`}
      onDrop={handleDrop}
      onDragOver={handleDragOver}
    >
      {/* 知识库引用 chips */}
      {knowledgeRefs.length > 0 && (
        <div className="flex flex-wrap gap-2 mb-2">
          {knowledgeRefs.map((k) => (
            <KnowledgeChip
              key={k.id}
              title={k.title}
              onRemove={() => toggleKnowledge(k.id, k.title)}
            />
          ))}
        </div>
      )}

      {/* 文件附件 */}
      {(files.length > 0 || images.length > 0) && (
        <div className="flex flex-wrap gap-2 mb-2">
          {[...files, ...images].map((f, i) => (
            <FileAttachment
              key={`${f.name}-${i}`}
              name={f.name}
              size={f.size}
              type={f.type}
              onRemove={() => {
                if (f.type.startsWith('image/')) {
                  removeImage(i - files.length);
                } else {
                  removeFile(i);
                }
              }}
            />
          ))}
        </div>
      )}

      <div className="flex items-end gap-2">
        <div className="flex-1 relative">
          {/* Phase 6 (M8 /btw): @ 文件提及浮层 */}
          {atQuery.query !== null && (
            <AtFileMenu
              query={atQuery.query}
              onSelect={(path) => {
                const newValue =
                  value.slice(0, atQuery.startIdx) + '@' + path + ' ' + value.slice(atQuery.endIdx);
                setValue(newValue);
                setCursorPos(atQuery.startIdx + 1 + path.length + 1);
              }}
              onClose={() => {
                const newValue = value.slice(0, atQuery.startIdx) + value.slice(atQuery.endIdx);
                setValue(newValue);
                setCursorPos(atQuery.startIdx);
              }}
            />
          )}
          <div className="border border-border rounded-radius-sm px-3 py-2 bg-bg flex items-end gap-2">
            <textarea
              ref={textareaRef}
              value={value}
              onChange={handleInput}
              onKeyDown={handleKeyDown}
              onKeyUp={(e) => setCursorPos((e.target as HTMLTextAreaElement).selectionStart ?? 0)}
              onClick={(e) => setCursorPos((e.target as HTMLTextAreaElement).selectionStart ?? 0)}
              placeholder={placeholder}
              disabled={disabled}
              rows={1}
              className="flex-1 bg-transparent border-none outline-none resize-none text-text placeholder:text-muted"
              style={{ maxHeight: '200px' }}
            />
            <div className="flex items-center gap-1">
              <button
                type="button"
                onClick={() => document.getElementById('chat-image-input')?.click()}
                title="图片"
                className="w-7 h-7 flex items-center justify-center rounded-radius-sm hover:bg-bg-hover text-muted hover:text-text transition-colors"
              >
                <Image className="w-4 h-4" />
              </button>
              <input
                id="chat-image-input"
                type="file"
                accept="image/*"
                multiple
                className="hidden"
                onChange={handleImageSelect}
              />
              <button
                type="button"
                onClick={() => document.getElementById('chat-file-input')?.click()}
                title="附件"
                className="w-7 h-7 flex items-center justify-center rounded-radius-sm hover:bg-bg-hover text-muted hover:text-text transition-colors"
              >
                <Paperclip className="w-4 h-4" />
              </button>
              <input
                id="chat-file-input"
                type="file"
                multiple
                className="hidden"
                onChange={handleImageSelect}
              />
              <button
                type="button"
                onClick={() => setShowKnowledgeSelector(!showKnowledgeSelector)}
                title="知识库"
                className="w-7 h-7 flex items-center justify-center rounded-radius-sm hover:bg-bg-hover text-muted hover:text-text transition-colors"
              >
                <BookOpen className="w-4 h-4" />
              </button>
              {onSchedule && (
                <button
                  type="button"
                  onClick={onSchedule}
                  title="定时"
                  className="w-7 h-7 flex items-center justify-center rounded-radius-sm hover:bg-bg-hover text-muted hover:text-text transition-colors"
                >
                  <Clock className="w-4 h-4" />
                </button>
              )}
            </div>
          </div>

          {/* 知识库选择器 */}
          {showKnowledgeSelector && (
            <div className="absolute bottom-full mb-2 left-0 right-0 max-h-60 overflow-y-auto bg-bg-elevated border border-border rounded-radius-sm shadow-lg p-2 z-10">
              {KNOWLEDGE_DOCS.map((doc) => {
                const selected = knowledgeRefs.find((k) => k.id === doc.id);
                return (
                  <button
                    key={doc.id}
                    type="button"
                    onClick={() => toggleKnowledge(doc.id, doc.title)}
                    className={`w-full text-left px-3 py-2 rounded-radius-sm transition-colors ${
                      selected
                        ? 'bg-primary text-text-inverse'
                        : 'hover:bg-bg-hover text-text'
                    }`}
                  >
                    <div className="font-medium">{doc.title}</div>
                    <div className="text-xs text-muted">{doc.desc}</div>
                  </button>
                );
              })}
            </div>
          )}
        </div>
        {isLoading ? (
          <button
            type="button"
            onClick={onInterrupt}
            title="停止"
            className="w-10 h-10 flex items-center justify-center bg-bg-elevated text-text rounded-radius-sm hover:bg-bg-hover transition-colors"
          >
            <Square className="w-4 h-4" />
          </button>
        ) : (
          <button
            type="button"
            onClick={handleSend}
            disabled={!value.trim() || disabled}
            className="w-10 h-10 flex items-center justify-center bg-primary text-text-inverse rounded-radius-sm hover:opacity-90 disabled:opacity-50 transition-opacity"
          >
            <Send className="w-4 h-4" />
          </button>
        )}
      </div>
    </div>
  );
}