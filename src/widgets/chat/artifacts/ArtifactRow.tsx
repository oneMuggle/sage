// src/widgets/chat/artifacts/ArtifactRow.tsx
import { FileText, FileCode, FileImage, FileSpreadsheet, File, ShieldCheck } from 'lucide-react';

import type { Artifact, ArtifactKind } from '../../../features/artifacts/artifactApi';

interface ArtifactRowProps {
  artifact: Artifact;
  onSelect: (artifact: Artifact) => void;
  onDoubleClick?: (artifact: Artifact) => void;
  onOpenDelivery?: (artifact: Artifact) => void;
}

const KIND_ICONS: Record<ArtifactKind, typeof File> = {
  markdown: FileText,
  code: FileCode,
  image: FileImage,
  csv: FileSpreadsheet,
  json: FileCode,
  pdf: FileText, // F11 (round4 批次 D)
  docx: FileText, // C-2 (round5 批次 C)
  xlsx: FileSpreadsheet,
  pptx: FileText,
  text: File,
};

const OFFICE_DELIVERY_KINDS: ReadonlySet<ArtifactKind> = new Set([
  'docx',
  'xlsx',
  'pptx',
  'pdf',
]);

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export function ArtifactRow({
  artifact,
  onSelect,
  onDoubleClick,
  onOpenDelivery,
}: ArtifactRowProps) {
  const Icon = KIND_ICONS[artifact.kind] ?? File;
  const canOpenDelivery = Boolean(onOpenDelivery && OFFICE_DELIVERY_KINDS.has(artifact.kind));
  return (
    <div className="w-full flex items-center gap-1 px-3 py-2 hover:bg-bg-hover rounded transition-colors">
      <button
        type="button"
        className="flex-1 min-w-0 flex items-center gap-2 text-left"
        onClick={() => onSelect(artifact)}
        onDoubleClick={() => onDoubleClick?.(artifact)}
      >
        <Icon className="w-4 h-4 text-text-secondary shrink-0" />
        <div className="flex-1 min-w-0">
          <div className="text-sm text-text truncate">{artifact.name}</div>
          <div className="text-xs text-muted">{formatSize(artifact.size)}</div>
        </div>
      </button>
      {canOpenDelivery && (
        <button
          type="button"
          className="p-1.5 rounded hover:bg-bg-tertiary text-text-secondary hover:text-primary shrink-0 transition-colors"
          title="打开交付工作台（格式质检 / 排版修复 / 前后对比）"
          aria-label={`打开 ${artifact.name} 交付工作台`}
          data-testid={`artifact-open-delivery-${artifact.id}`}
          onClick={(e) => {
            e.stopPropagation();
            onOpenDelivery?.(artifact);
          }}
        >
          <ShieldCheck className="w-4 h-4" />
        </button>
      )}
    </div>
  );
}
