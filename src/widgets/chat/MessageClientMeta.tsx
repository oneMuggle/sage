// src/widgets/chat/MessageClientMeta.tsx
//
// 用户消息引用信息 chips —— 附件 / @ 文件引用 / office 文档 / 知识库。
// 优先读取消息自带的 client_meta（刷新后由 get_messages 回读），兼容旧调用
// 方通过 MessageList props 传入的 knowledgeRefs / attachments 映射。
import { BookOpen, FileText } from 'lucide-react';

import type { MessageDisplayMeta, MessageDisplayOfficeRef } from '../../shared/api/types';
import type { Message } from '../../shared/lib/store';

interface MessageClientMetaProps {
  message: Message;
  isUser: boolean;
  knowledgeRefs?: { id: string; title: string }[];
  attachments?: { name: string; size: number; type: string; dataUrl?: string }[];
}

function officeKindLabel(docType: MessageDisplayOfficeRef['doc_type']): string {
  switch (docType) {
    case 'ppt':
      return '📊';
    case 'word':
      return '📝';
    case 'pdf':
      return '📄';
    default:
      return '📈';
  }
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
  const meta = message.client_meta ?? null;
  const effectiveKnowledge = knowledgeRefs ?? meta?.knowledge_refs ?? [];
  const effectiveAttachments = attachments ?? [
    ...(meta?.attachments ?? []),
    ...(meta?.images ?? []),
  ];
  const fileRefs = meta?.file_refs ?? [];
  const officeRefs = meta?.office_refs ?? [];
  if (!hasAnyRefs(meta, effectiveKnowledge.length, effectiveAttachments.length)) return null;

  return (
    <div
      data-testid="message-client-meta"
      className={`flex flex-wrap gap-1.5 mb-1 ${isUser ? 'justify-end' : ''}`}
    >
      {fileRefs.map((ref) => (
        <span
          key={`file-${ref.path}`}
          data-testid="message-file-ref"
          title={ref.path}
          className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-ui-2xs border border-border bg-bg-subtle text-text-secondary"
        >
          <FileText className="w-3 h-3 shrink-0" />
          <span className="truncate max-w-48">{ref.path}</span>
        </span>
      ))}
      {officeRefs.map((ref) => (
        <span
          key={`office-${ref.doc_id}`}
          data-testid="message-office-ref"
          title={ref.filename}
          className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-ui-2xs border border-border bg-bg-subtle text-text-secondary"
        >
          <span aria-hidden="true">{officeKindLabel(ref.doc_type)}</span>
          <span className="truncate max-w-48">{ref.filename}</span>
        </span>
      ))}
      {effectiveKnowledge.map((ref) => (
        <span
          key={`knowledge-${ref.id}`}
          data-testid="message-knowledge-ref"
          className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-ui-2xs bg-primary/10 text-primary"
        >
          <BookOpen className="w-2.5 h-2.5" />
          {ref.title}
        </span>
      ))}
      {effectiveAttachments.map((file, idx) => (
        <span
          key={`attachment-${file.name}-${idx}`}
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
      ))}
    </div>
  );
}
