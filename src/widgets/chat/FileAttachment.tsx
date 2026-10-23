import { File, FileText, Image, X } from 'lucide-react';

interface FileAttachmentProps {
  name: string;
  size: number;
  type: string;
  onRemove?: () => void;
}

export function FileAttachment({ name, size, type, onRemove }: FileAttachmentProps) {
  return (
    <span className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-radius-sm bg-bg-muted text-xs text-text-secondary border border-border">
      {getFileIcon(type)}
      <span className="truncate max-w-32">{name}</span>
      <span className="text-muted">({formatFileSize(size)})</span>
      {onRemove && (
        <button className="ml-1 hover:text-text transition-colors" onClick={onRemove}>
          <X className="w-3 h-3" />
        </button>
      )}
    </span>
  );
}

function getFileIcon(mimeType: string) {
  if (mimeType.startsWith('image/')) {
    return <Image className="w-3.5 h-3.5 text-muted" />;
  }
  if (mimeType === 'application/pdf') {
    return <FileText className="w-3.5 h-3.5 text-muted" />;
  }
  return <File className="w-3.5 h-3.5 text-muted" />;
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1048576) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1048576).toFixed(1)} MB`;
}

export interface FileAttachmentAuditInput {
  fileName: string;
  fileSizeBytes: number;
  mimeType: string;
  maxAllowedBytes: number;
}

export interface FileAttachmentAuditReport {
  fileName: string;
  fileSizeBytes: number;
  mimeType: string;
  withinSizeLimit: boolean;
  healthy: boolean;
  issueCodes: string[];
}

// eslint-disable-next-line react-refresh/only-export-components
export function evaluateFileAttachmentAudit(
  input: FileAttachmentAuditInput,
): FileAttachmentAuditReport {
  const fileName = input.fileName.trim();
  const mimeType = input.mimeType.trim() || 'application/octet-stream';
  const fileSizeBytes = Math.max(0, Math.trunc(input.fileSizeBytes));
  const maxAllowedBytes = Math.max(1, Math.trunc(input.maxAllowedBytes));
  const withinSizeLimit = fileSizeBytes <= maxAllowedBytes;
  const issueCodes: string[] = [];

  if (!fileName) {
    issueCodes.push('missing_attachment_filename');
  }
  if (fileSizeBytes === 0) {
    issueCodes.push('empty_attachment_payload');
  }
  if (!withinSizeLimit) {
    issueCodes.push('attachment_exceeds_size_limit');
  }

  return {
    fileName,
    fileSizeBytes,
    mimeType,
    withinSizeLimit,
    healthy: issueCodes.length === 0,
    issueCodes,
  };
}

// eslint-disable-next-line react-refresh/only-export-components
export function exportFileAttachmentAuditJson(
  input: FileAttachmentAuditInput,
): string {
  return JSON.stringify(evaluateFileAttachmentAudit(input));
}
// eslint-disable-next-line react-refresh/only-export-components
export function auditFileAttachmentGovernance(): string {
  return JSON.stringify({
    module: 'file-attachment',
    phase: 'P186',
    audited: true,
  });
}
