// src/widgets/chat/artifacts/VersionHistory.tsx
import { useCallback, useEffect, useState } from 'react';
import { History, RotateCcw } from 'lucide-react';

import {
  listArtifactVersions,
  restoreArtifactVersion,
  type ArtifactVersion,
} from '../../../features/artifacts/artifactApi';

interface VersionHistoryProps {
  sessionId: string;
  artifactId: string;
  onRestoreComplete?: (newVersion: ArtifactVersion) => void;
}

function formatTimestamp(ms: number): string {
  const d = new Date(ms);
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export function VersionHistory({ sessionId, artifactId, onRestoreComplete }: VersionHistoryProps) {
  const [versions, setVersions] = useState<ArtifactVersion[]>([]);
  const [loading, setLoading] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [restoring, setRestoring] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const list = await listArtifactVersions(sessionId, artifactId);
      setVersions(list);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [sessionId, artifactId]);

  useEffect(() => {
    if (expanded) {
      void reload();
    }
  }, [expanded, reload]);

  const handleRestore = async (versionNum: number) => {
    setRestoring(versionNum);
    setError(null);
    try {
      const result = await restoreArtifactVersion(sessionId, artifactId, versionNum);
      onRestoreComplete?.(result.new_version);
      await reload();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRestoring(null);
    }
  };

  return (
    <div className="border-t border-border">
      <button
        type="button"
        className="flex items-center gap-1.5 w-full px-3 py-1.5 text-xs text-muted hover:bg-bg-hover transition-colors"
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={expanded}
      >
        <History className="w-3.5 h-3.5" />
        <span>版本历史</span>
        {versions.length > 0 && (
          <span className="ml-auto text-text-secondary">({versions.length})</span>
        )}
      </button>

      {expanded && (
        <div className="px-3 pb-2">
          {loading ? (
            <div className="text-xs text-muted py-2">加载版本列表…</div>
          ) : error ? (
            <div className="text-xs text-error py-2">{error}</div>
          ) : versions.length === 0 ? (
            <div className="text-xs text-muted py-2">尚无版本记录</div>
          ) : (
            <ul className="space-y-1 max-h-40 overflow-auto">
              {versions.map((v) => (
                <li
                  key={v.version_num}
                  className="flex items-center gap-2 text-xs py-1 px-1 rounded hover:bg-bg-hover group"
                >
                  <span className="text-text-secondary w-8 shrink-0">v{v.version_num}</span>
                  <span className="text-muted shrink-0">{formatTimestamp(v.created_at)}</span>
                  {v.note && (
                    <span className="truncate text-text-secondary" title={v.note}>
                      {v.note}
                    </span>
                  )}
                  <button
                    type="button"
                    className="ml-auto p-1 rounded opacity-0 group-hover:opacity-100 hover:bg-border transition-opacity"
                    title={`恢复到 v${v.version_num}`}
                    disabled={restoring !== null}
                    onClick={() => void handleRestore(v.version_num)}
                  >
                    <RotateCcw
                      className={`w-3 h-3 ${restoring === v.version_num ? 'animate-spin' : ''}`}
                    />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
