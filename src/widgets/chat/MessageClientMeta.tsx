// src/widgets/chat/MessageClientMeta.tsx
//
// 用户消息引用信息 chips —— 附件 / @ 文件引用 / office 文档 / 知识库。
// 优先读取消息自带的 client_meta（刷新后由 get_messages 回读），兼容旧调用
// 方通过 MessageList props 传入的 knowledgeRefs / attachments 映射。
// 每个 chip 提供右键菜单（复制路径/文件名、Office 打开与定位、查看大图）。
import { BookOpen, Copy, FileText, Maximize2 } from 'lucide-react';
import { useState } from 'react';

import type { MessageDisplayFileRef, MessageDisplayMeta } from '../../shared/api/types';
import { copyToClipboard } from '../../shared/lib/clipboard';
import { useI18n } from '../../shared/lib/i18n';
import type { Message } from '../../shared/lib/store';
import { Lightbox } from '../../shared/ui';
import { ContextMenu } from '../../shared/ui/ContextMenu/ContextMenu';
import type { ContextMenuItemSpec } from '../../shared/ui/ContextMenu/types';

import { OfficeRefChip } from './OfficeRefChip';

interface MessageClientMetaProps {
  message: Message;
  isUser: boolean;
  knowledgeRefs?: { id: string; title: string }[];
  attachments?: { name: string; size: number; type: string; dataUrl?: string }[];
}

function hasAnyRefs(
  meta: MessageDisplayMeta | null,
  knowledgeCount: number,
  attachmentCount: number,
): boolean {
  return (
    (meta?.file_refs?.length ?? 0) > 0 ||
    (meta?.office_refs?.length ?? 0) > 0 ||
    knowledgeCount > 0 ||
    attachmentCount > 0
  );
}

export function MessageClientMeta({
  message,
  isUser,
  knowledgeRefs,
  attachments,
}: MessageClientMetaProps) {
  const { t } = useI18n();
  const [lightboxSrc, setLightboxSrc] = useState<string | null>(null);
  const meta = message.client_meta ?? null;
  const effectiveKnowledge = knowledgeRefs ?? meta?.knowledge_refs ?? [];
  const effectiveAttachments = attachments ?? [
    ...(meta?.attachments ?? []),
    ...(meta?.images ?? []),
  ];
  const fileRefs = meta?.file_refs ?? [];
  const officeRefs = meta?.office_refs ?? [];
  if (!hasAnyRefs(meta, effectiveKnowledge.length, effectiveAttachments.length)) return null;

  const copy = (text: string) =>
    void copyToClipboard(text, {
      successMessage: t('contextMenu.common.copied'),
      errorMessage: t('contextMenu.common.copyFailed'),
    });

  const fileRefMenu = (ref: MessageDisplayFileRef): ContextMenuItemSpec[] => [
    {
      id: 'copy-path',
      label: t('contextMenu.common.copyPath'),
      icon: Copy,
      onSelect: () => copy(ref.path),
    },
    {
      id: 'copy-name',
      label: t('contextMenu.common.copyName'),
      icon: FileText,
      onSelect: () => copy(ref.name),
    },
  ];

  const knowledgeMenu = (title: string): ContextMenuItemSpec[] => [
    {
      id: 'copy-title',
      label: t('contextMenu.common.copyName'),
      icon: Copy,
      onSelect: () => copy(title),
    },
  ];

  const attachmentMenu = (file: {
    name: string;
    type: string;
    dataUrl?: string;
  }): ContextMenuItemSpec[] => [
    {
      id: 'copy-attachment-name',
      label: t('contextMenu.common.copyName'),
      icon: Copy,
      onSelect: () => copy(file.name),
    },
    ...(file.type.startsWith('image/') && file.dataUrl
      ? [
          {
            id: 'view-attachment',
            label: t('contextMenu.image.view'),
            icon: Maximize2,
            onSelect: () => setLightboxSrc(file.dataUrl ?? null),
          },
        ]
      : []),
  ];

  return (
    <div
      data-testid="message-client-meta"
      className={`flex flex-wrap gap-1.5 mb-1 ${isUser ? 'justify-end' : ''}`}
    >
      {fileRefs.map((ref) => (
        <ContextMenu key={`file-${ref.path}`} items={() => fileRefMenu(ref)}>
          <span
            data-testid="message-file-ref"
            title={ref.path}
            className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-ui-2xs border border-border bg-bg-subtle text-text-secondary"
          >
            <FileText className="w-3 h-3 shrink-0" />
            <span className="truncate max-w-48">{ref.path}</span>
          </span>
        </ContextMenu>
      ))}
      {officeRefs.map((ref) => (
        <OfficeRefChip
          key={`office-${ref.doc_id}`}
          chip={{
            docId: ref.doc_id,
            docType: ref.doc_type,
            filename: ref.filename,
            workspacePath: ref.workspace_path,
          }}
          variant="message"
        />
      ))}
      {effectiveKnowledge.map((ref) => (
        <ContextMenu key={`knowledge-${ref.id}`} items={() => knowledgeMenu(ref.title)}>
          <span
            data-testid="message-knowledge-ref"
            className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-ui-2xs bg-primary/10 text-primary"
          >
            <BookOpen className="w-2.5 h-2.5" />
            {ref.title}
          </span>
        </ContextMenu>
      ))}
      {effectiveAttachments.map((file, idx) => (
        <ContextMenu key={`attachment-${file.name}-${idx}`} items={() => attachmentMenu(file)}>
          <span
            data-testid="message-attachment-ref"
            title={file.name}
            className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-ui-2xs border ${
              isUser
                ? 'bg-text-inverse/15 border-text-inverse/20 text-text-inverse'
                : 'bg-bg-subtle border-border text-text-secondary'
            }`}
          >
            {file.type.startsWith('image/') && file.dataUrl ? (
              <img src={file.dataUrl} alt="" className="w-4 h-4 rounded object-cover" />
            ) : (
              <FileText className="w-3 h-3 shrink-0" />
            )}
            <span className="truncate max-w-48">{file.name}</span>
          </span>
        </ContextMenu>
      ))}
      {lightboxSrc && <Lightbox src={lightboxSrc} alt="" onClose={() => setLightboxSrc(null)} />}
    </div>
  );
}
