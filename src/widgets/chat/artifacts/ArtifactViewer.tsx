// src/widgets/chat/artifacts/ArtifactViewer.tsx
import { ArrowLeft, Copy, FolderOpen } from 'lucide-react';
import type { Artifact } from '../../../features/artifacts/artifactApi';
import { revealArtifact } from '../../../features/artifacts/artifactApi';
import { useArtifactContent } from '../../../features/artifacts/useArtifactContent';

interface ArtifactViewerProps {
  artifact: Artifact;
  sessionId: string;
  onBack: () => void;
}

function parseCsv(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = '';
  let quoted = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (quoted) {
      if (ch === '"') {
        if (text[i + 1] === '"') { cell += '"'; i++; } else quoted = false;
      } else cell += ch;
    } else if (ch === '"') quoted = true;
    else if (ch === ',') { row.push(cell); cell = ''; }
    else if (ch === '\n' || ch === '\r') {
      if (ch === '\r' && text[i + 1] === '\n') i++;
      row.push(cell); rows.push(row); row = []; cell = '';
    }
    else cell += ch;
  }
  if (cell !== '' || row.length) { row.push(cell); rows.push(row); }
  return rows.filter((r) => r.some((c) => c !== ''));
}

function CsvPreview({ text }: { text: string }) {
  const rows = parseCsv(text);
  if (rows.length === 0) return <div className="text-sm text-muted">空文件</div>;
  const [head, ...body] = rows;
  return (
    <div className="overflow-auto">
      <table className="text-xs border-collapse">
        <thead>
          <tr>{head.map((c, i) => <th key={i} className="border px-2 py-1 bg-bg-hover">{c}</th>)}</tr>
        </thead>
        <tbody>
          {body.slice(0, 500).map((r, i) => (
            <tr key={i}>{r.map((c, j) => <td key={j} className="border px-2 py-1">{c}</td>)}</tr>
          ))}
        </tbody>
      </table>
      {body.length > 500 && <div className="text-xs text-muted mt-2">仅显示前 500 行</div>}
    </div>
  );
}

export function ArtifactViewer({ artifact, sessionId, onBack }: ArtifactViewerProps) {
  const { content, loading } = useArtifactContent(sessionId, artifact.id);

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center gap-2 px-2 py-1 border-b border-border">
        <button className="p-1.5 rounded hover:bg-bg-hover" onClick={onBack} aria-label="返回">
          <ArrowLeft className="w-4 h-4" />
        </button>
        <div className="flex-1 min-w-0 text-sm">
          <span className="text-muted">产物</span>
          <span className="mx-1 text-muted">/</span>
          <span className="text-text">{artifact.name}</span>
        </div>
        <button
          className="p-1.5 rounded hover:bg-bg-hover"
          title="复制路径"
          onClick={() => { void navigator.clipboard?.writeText(artifact.path)?.catch(() => {}); }}
        >
          <Copy className="w-4 h-4" />
        </button>
        <button
          className="p-1.5 rounded hover:bg-bg-hover"
          title="在文件管理器中显示"
          onClick={() => { revealArtifact(sessionId, artifact.id).catch(() => {}); }}
        >
          <FolderOpen className="w-4 h-4" />
        </button>
      </div>

      <div className="flex-1 overflow-auto p-3">
        {loading ? (
          <div className="text-sm text-muted">加载中...</div>
        ) : !content || !content.ok ? (
          <div className="text-sm text-error">{content?.error ?? '加载失败'}</div>
        ) : content.kind === 'image' ? (
          <img src={content.data_url} alt={artifact.name} className="max-w-full" />
        ) : content.kind === 'code' || content.kind === 'json' ? (
          <pre className="whitespace-pre-wrap text-xs font-mono bg-bg-hover p-2 rounded">{content.content}</pre>
        ) : content.kind === 'csv' ? (
          <CsvPreview text={content.content ?? ''} />
        ) : (
          <pre className="whitespace-pre-wrap text-sm">{content.content}</pre>
        )}
      </div>
    </div>
  );
}
