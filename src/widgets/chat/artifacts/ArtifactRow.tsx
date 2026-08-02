// src/widgets/chat/artifacts/ArtifactRow.tsx
import { FileText, FileCode, FileImage, FileSpreadsheet, File } from 'lucide-react';

import type { Artifact, ArtifactKind } from '../../../features/artifacts/artifactApi';

interface ArtifactRowProps {
  artifact: Artifact;
  onSelect: (artifact: Artifact) => void;
}

const KIND_ICONS: Record<ArtifactKind, typeof File> = {
  markdown: FileText,
  code: FileCode,
  image: FileImage,
  csv: FileSpreadsheet,
  json: FileCode,
  text: File,
};

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export function ArtifactRow({ artifact, onSelect }: ArtifactRowProps) {
  const Icon = KIND_ICONS[artifact.kind] ?? File;
  return (
    <button
      className="w-full flex items-center gap-2 px-3 py-2 hover:bg-bg-hover rounded text-left transition-colors"
      onClick={() => onSelect(artifact)}
    >
      <Icon className="w-4 h-4 text-text-secondary shrink-0" />
      <div className="flex-1 min-w-0">
        <div className="text-sm text-text truncate">{artifact.name}</div>
        <div className="text-xs text-muted">{formatSize(artifact.size)}</div>
      </div>
    </button>
  );
}
