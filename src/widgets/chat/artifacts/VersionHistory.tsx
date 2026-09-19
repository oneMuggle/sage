// src/widgets/chat/artifacts/VersionHistory.tsx
import { GitCompare, History, RotateCcw } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';

import {
  getArtifactVersion,
  listArtifactVersions,
  readArtifactContent,
  restoreArtifactVersion,
  type ArtifactVersion,
} from '../../../features/artifacts/artifactApi';
import { unifiedDiff } from '../../../shared/lib/unifiedDiff';
import { SplitDiff } from '../changes/SplitDiff';

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
  // right-panel R3 批次 A: 版本 diff —— diffFor = 正在展开对比的版本号
  // right-panel R4 批次 A: diffAgainst = 对比右侧（'current' | 任意版本号）
  const [diffFor, setDiffFor] = useState<number | null>(null);
  const [diffAgainst, setDiffAgainst] = useState<'current' | number>('current');
  const [diffText, setDiffText] = useState<string | null>(null);
  const [diffLoading, setDiffLoading] = useState(false);

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

  // right-panel R3 批次 A: 展开/收起 指定版本 的 diff（R4 批次 A: 右侧可选）
  const toggleDiff = async (versionNum: number) => {
    if (diffFor === versionNum) {
      setDiffFor(null);
      setDiffText(null);
      return;
    }
    setDiffFor(versionNum);
    setDiffAgainst('current');
    await buildDiff(versionNum, 'current');
  };

  // right-panel R4 批次 A: 版本互比 —— 左固定 diffFor，右侧 'current' 或
  // 任意其它版本；任一侧拉取失败只影响当前对比
  const buildDiff = async (
    leftVersion: number,
    against: 'current' | number,
  ) => {
    setDiffLoading(true);
    setError(null);
    try {
      const left = await getArtifactVersion(sessionId, artifactId, leftVersion);
      const rightLabel =
        against === 'current' ? '当前版本' : `v${against}`;
      const right = await (against === 'current'
        ? readArtifactContent(sessionId, artifactId).then((c) => ({
            created_at: 0,
            content: c.content ?? '',
          }))
        : getArtifactVersion(sessionId, artifactId, against).then((v) => ({
            created_at: v.created_at,
            content: v.content ?? '',
          })));
      const diff = unifiedDiff(left.content ?? '', right.content, {
        oldLabel: `v${leftVersion} (${left.created_at ? new Date(left.created_at).toISOString().slice(0, 16).replace('T', ' ') : ''})`,
        newLabel: rightLabel,
      });
      setDiffText(diff === '' ? '（两个版本内容相同）' : diff);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
      setDiffFor(null);
    } finally {
      setDiffLoading(false);
    }
  };

  // R4 批次 A: 更换对比右侧
  const changeDiffAgainst = async (against: 'current' | number) => {
    if (diffFor === null) return;
    setDiffAgainst(against);
    await buildDiff(diffFor, against);
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
                  className="text-xs rounded hover:bg-bg-hover group"
                >
                  <div className="flex items-center gap-2 py-1 px-1">
                    <span className="text-text-secondary w-8 shrink-0">v{v.version_num}</span>
                    <span className="text-muted shrink-0">{formatTimestamp(v.created_at)}</span>
                    {v.note && (
                      <span className="truncate text-text-secondary" title={v.note}>
                        {v.note}
                      </span>
                    )}
                    <span className="ml-auto flex items-center gap-0.5 opacity-0 group-hover:opacity-100">
                      <button
                        type="button"
                        className={
                          'p-1 rounded hover:bg-border transition-opacity ' +
                          (diffFor === v.version_num ? 'text-primary' : '')
                        }
                        title={`对比 v${v.version_num} 与当前内容`}
                        aria-label={`对比 v${v.version_num} 与当前内容`}
                        data-testid={`version-diff-toggle-${v.version_num}`}
                        disabled={diffLoading}
                        onClick={() => void toggleDiff(v.version_num)}
                      >
                        <GitCompare
                          className={`w-3 h-3 ${diffLoading && diffFor === v.version_num ? 'animate-pulse' : ''}`}
                        />
                      </button>
                      <button
                        type="button"
                        className="p-1 rounded hover:bg-border transition-opacity"
                        title={`恢复到 v${v.version_num}`}
                        disabled={restoring !== null}
                        onClick={() => void handleRestore(v.version_num)}
                      >
                        <RotateCcw
                          className={`w-3 h-3 ${restoring === v.version_num ? 'animate-spin' : ''}`}
                        />
                      </button>
                    </span>
                  </div>
                  {diffFor === v.version_num && (
                    <div
                      className="px-1 pb-2"
                      data-testid={`version-diff-view-${v.version_num}`}
                    >
                      {/* R4 批次 A: 对比右侧可选（当前版本 / 任意其它版本） */}
                      <div className="flex items-center gap-1.5 py-1">
                        <span className="text-muted shrink-0">对比对象</span>
                        <select
                          className="text-xs bg-surface border border-border rounded px-1 py-0.5 text-text"
                          value={diffAgainst === 'current' ? 'current' : String(diffAgainst)}
                          aria-label="选择对比对象版本"
                          data-testid={`version-diff-against-${v.version_num}`}
                          disabled={diffLoading}
                          onChange={(e) => {
                            const val = e.target.value;
                            void changeDiffAgainst(val === 'current' ? 'current' : Number(val));
                          }}
                        >
                          <option value="current">当前版本</option>
                          {versions
                            .filter((o) => o.version_num !== v.version_num)
                            .map((o) => (
                              <option key={o.version_num} value={o.version_num}>
                                v{o.version_num}
                              </option>
                            ))}
                        </select>
                      </div>
                      {diffLoading ? (
                        <div className="text-muted py-1">加载对比…</div>
                      ) : diffText ? (
                        diffText === '（两个版本内容相同）' ? (
                          <div className="text-muted py-1">{diffText}</div>
                        ) : (
                          <div className="border border-border rounded overflow-auto">
                            <SplitDiff diff={diffText} />
                          </div>
                        )
                      ) : null}
                    </div>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
