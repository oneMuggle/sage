import { BookOpen, Image, Paperclip, Send, Square } from 'lucide-react';
import type React from 'react';

import { useI18n } from '../../shared/lib/i18n';

import { FileAttachment } from './FileAttachment';
import { KnowledgeChip } from './KnowledgeChip';
import { SlashCommandMenu } from './SlashCommandMenu';
import type { SlashCommand } from './slashCommands';

export interface FileAttachmentType {
  name: string;
  size: number;
  type: string;
  dataUrl?: string;
}

export type ImageAttachmentType = FileAttachmentType;

export interface KnowledgeRefType {
  id: string;
  title: string;
}

export interface KnowledgeDocType {
  id: string;
  title: string;
  desc: string;
}

export interface InputCardProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  placeholder?: string;
  disabled?: boolean;
  isLoading?: boolean;
  onInterrupt?: () => void;
  autoFocus?: boolean;

  // Attachments
  files?: FileAttachmentType[];
  images?: ImageAttachmentType[];
  knowledgeRefs?: KnowledgeRefType[];
  onRemoveFile?: (idx: number) => void;
  onRemoveImage?: (idx: number) => void;
  onRemoveKnowledge?: (idx: number) => void;

  // Knowledge selector
  knowledgeDocs?: KnowledgeDocType[];
  showKnowledgeSelector?: boolean;
  onToggleKnowledgeSelector?: (show: boolean) => void;
  onToggleKnowledge?: (docId: string) => void;

  // File/image picker
  onImageSelect?: (e: React.ChangeEvent<HTMLInputElement>) => void;
  onFileSelect?: (e: React.ChangeEvent<HTMLInputElement>) => void;

  // Drag & drop
  onDrop?: (e: React.DragEvent) => void;
  onDragOver?: (e: React.DragEvent) => void;
  isDragOver?: boolean;

  // Slash menu
  showSlashMenu?: boolean;
  slashCommands?: SlashCommand[];
  slashSelectedIndex?: number;
  onSlashSelect?: (cmd: SlashCommand) => void;

  // At file menu (for @mentions)
  atFileMenu?: React.ReactNode;

  // Footer hint
  hint?: string;
}

export function InputCard({
  value,
  onChange,
  onSubmit,
  placeholder = '',
  disabled = false,
  isLoading = false,
  onInterrupt,
  autoFocus = false,
  files = [],
  images = [],
  knowledgeRefs = [],
  onRemoveFile,
  onRemoveImage,
  onRemoveKnowledge,
  knowledgeDocs = [],
  showKnowledgeSelector = false,
  onToggleKnowledgeSelector,
  onToggleKnowledge,
  onImageSelect,
  onFileSelect,
  onDrop,
  onDragOver,
  isDragOver = false,
  showSlashMenu = false,
  slashCommands = [],
  slashSelectedIndex = 0,
  onSlashSelect,
  atFileMenu,
  hint,
}: InputCardProps) {
  const { t } = useI18n();
  const hasAttachments = files.length > 0 || images.length > 0 || knowledgeRefs.length > 0;

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (showSlashMenu && slashCommands.length > 0 && !e.shiftKey) {
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        return;
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault();
        return;
      }
      if (e.key === 'Enter') {
        e.preventDefault();
        const cmd = slashCommands[slashSelectedIndex];
        if (cmd) onSlashSelect?.(cmd);
        return;
      }
      if (e.key === 'Escape') {
        e.preventDefault();
        return;
      }
    }
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      onSubmit();
    }
  };

  return (
    <div
      className="p-4 border border-border rounded-radius-md bg-surface relative shadow-sm"
      onDrop={onDrop}
      onDragOver={onDragOver}
    >
      {isDragOver && (
        <div className="absolute inset-0 bg-primary/10 border-2 border-dashed border-primary rounded-radius-md flex items-center justify-center z-10">
          <p className="text-primary font-medium">{t('chat.drop_files')}</p>
        </div>
      )}

      {images.length > 0 && (
        <div className="flex gap-2 mb-2">
          {images.map((img, idx) => (
            <div
              key={idx}
              className="relative w-14 h-14 rounded-radius-sm border border-border overflow-hidden"
            >
              {img.dataUrl && (
                <img src={img.dataUrl} alt="" className="w-full h-full object-cover" />
              )}
              {onRemoveImage && (
                <button
                  type="button"
                  className="absolute top-0.5 right-0.5 w-4 h-4 rounded-full bg-text/80 text-text-inverse flex items-center justify-center text-xs"
                  onClick={() => onRemoveImage(idx)}
                  aria-label="remove image"
                >
                  ×
                </button>
              )}
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
              onRemove={onRemoveKnowledge ? () => onRemoveKnowledge(idx) : undefined}
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
              onRemove={onRemoveFile ? () => onRemoveFile(idx) : undefined}
            />
          ))}
        </div>
      )}

      <div className="flex items-end gap-2">
        <div className="flex-1 relative">
          {showSlashMenu && slashCommands.length > 0 && onSlashSelect && (
            <SlashCommandMenu
              commands={slashCommands}
              selectedIndex={slashSelectedIndex}
              onSelect={onSlashSelect}
            />
          )}
          {atFileMenu}
          <div className="border border-border rounded-radius-sm px-3 py-2 bg-bg flex items-end gap-2">
            <textarea
              value={value}
              onChange={(e) => onChange(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={placeholder}
              disabled={disabled}
              autoFocus={autoFocus}
              rows={1}
              className="flex-1 resize-none border-none bg-transparent outline-none text-sm text-text disabled:opacity-50 max-h-[200px] placeholder:text-muted"
              aria-label="message input"
            />

            <div className="flex items-center gap-1 flex-shrink-0">
              <button
                type="button"
                className="w-7 h-7 flex items-center justify-center rounded-radius-sm hover:bg-bg-hover text-muted hover:text-text transition-colors"
                title={t('chat.attach_image')}
                onClick={() => document.getElementById('chat-input-image')?.click()}
              >
                <Image className="w-4 h-4" />
              </button>
              <button
                type="button"
                className="w-7 h-7 flex items-center justify-center rounded-radius-sm hover:bg-bg-hover text-muted hover:text-text transition-colors"
                title={t('chat.attach_file')}
                onClick={() => document.getElementById('chat-input-file')?.click()}
              >
                <Paperclip className="w-4 h-4" />
              </button>
              {onToggleKnowledgeSelector && (
                <button
                  type="button"
                  className="w-7 h-7 flex items-center justify-center rounded-radius-sm hover:bg-bg-hover text-muted hover:text-text transition-colors"
                  title={t('chat.knowledge_ref')}
                  onClick={() => onToggleKnowledgeSelector(!showKnowledgeSelector)}
                >
                  <BookOpen className="w-4 h-4" />
                </button>
              )}
            </div>
          </div>

          {showKnowledgeSelector && knowledgeDocs.length > 0 && onToggleKnowledge && (
            <div className="absolute bottom-full left-0 mb-2 w-72 bg-surface border border-border rounded-radius-md shadow-lg z-20">
              <div className="p-3">
                <p className="text-xs font-medium text-text mb-2">{t('chat.knowledge_docs')}</p>
                {knowledgeDocs.map((doc) => {
                  const isSelected = !!knowledgeRefs.find((r) => r.id === doc.id);
                  return (
                    <button
                      key={doc.id}
                      type="button"
                      className={`w-full text-left px-2 py-1.5 rounded text-xs flex items-center gap-2 transition-colors ${
                        isSelected
                          ? 'bg-primary/10 text-primary'
                          : 'hover:bg-bg-hover text-text-secondary'
                      }`}
                      onClick={() => onToggleKnowledge(doc.id)}
                    >
                      <span
                        className={`w-3.5 h-3.5 rounded border flex items-center justify-center flex-shrink-0 ${
                          isSelected ? 'bg-primary border-primary' : 'border-border'
                        }`}
                      >
                        {isSelected && (
                          <svg
                            width="8"
                            height="8"
                            viewBox="0 0 24 24"
                            fill="none"
                            stroke="white"
                            strokeWidth="4"
                          >
                            <polyline points="20 6 9 17 4 12" />
                          </svg>
                        )}
                      </span>
                      <div>
                        <div className="font-medium">{doc.title}</div>
                        <div className="text-muted">{doc.desc}</div>
                      </div>
                    </button>
                  );
                })}
              </div>
            </div>
          )}
        </div>

        {isLoading ? (
          <button
            type="button"
            onClick={onInterrupt}
            title={t('chat.stop')}
            className="h-9 px-4 bg-error text-text-inverse border-none rounded-radius-sm text-sm font-medium cursor-pointer flex items-center gap-1.5 hover:bg-error/90 transition-colors"
          >
            <Square className="w-3.5 h-3.5" />
          </button>
        ) : (
          <button
            type="button"
            onClick={onSubmit}
            disabled={(!value.trim() && !hasAttachments) || disabled}
            className="h-9 px-4 bg-primary text-text-inverse border-none rounded-radius-sm text-sm font-medium cursor-pointer flex items-center gap-1.5 hover:bg-primary-hover disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {t('chat.send')}
            <Send className="w-3.5 h-3.5" />
          </button>
        )}
      </div>

      {onImageSelect && (
        <input
          type="file"
          id="chat-input-image"
          accept="image/*"
          multiple
          className="hidden"
          onChange={onImageSelect}
        />
      )}
      {onFileSelect && (
        <input
          type="file"
          id="chat-input-file"
          multiple
          className="hidden"
          onChange={onFileSelect}
        />
      )}

      {hint && <p className="text-[11px] text-muted text-center mt-1.5">{hint}</p>}
    </div>
  );
}
