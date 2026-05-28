import { File, FileText, Image, X } from 'lucide-react'

interface FileAttachmentProps {
  name: string
  size: number
  type: string
  onRemove?: () => void
}

export function FileAttachment({ name, size, type, onRemove }: FileAttachmentProps) {
  return (
    <span className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-radius-sm bg-bg-muted text-xs text-text-secondary border border-border">
      {getFileIcon(type)}
      <span className="truncate max-w-32">{name}</span>
      <span className="text-muted">({formatFileSize(size)})</span>
      {onRemove && (
        <button
          className="ml-1 hover:text-text transition-colors"
          onClick={onRemove}
        >
          <X className="w-3 h-3" />
        </button>
      )}
    </span>
  )
}

function getFileIcon(mimeType: string) {
  if (mimeType.startsWith('image/')) {
    return <Image className="w-3.5 h-3.5 text-muted" />
  }
  if (mimeType === 'application/pdf') {
    return <FileText className="w-3.5 h-3.5 text-muted" />
  }
  return <File className="w-3.5 h-3.5 text-muted" />
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1048576) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1048576).toFixed(1)} MB`
}
