/**
 * Zotero 索引/同步面板（M5）。
 *
 * 职责：
 * - 展示索引状态（已索引条目 / wiki 页面 / 上次同步时间）
 * - 「立即同步」（增量）与「完整重建」（force=true）
 * - wiki 沉淀标签配置（`zotero_wiki_tag` preferences KV）
 * - embedding 未配置时给出引导
 *
 * 项目解析：同步只在传入 `project_path` 时沉淀 wiki。设置页没有项目上下文，
 * 因此优先用已打开的 wiki 项目（`useWikiStore.project`），回退到最近打开的
 * 项目；都没有时只建索引，并在 UI 提示 wiki 沉淀需要先打开项目。
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { toast } from 'sonner';

import { useWikiStore } from '../../../entities/wiki/store';
import {
  DEFAULT_WIKI_TAG,
  zoteroClient,
  type ZoteroSyncResult,
  type ZoteroSyncStatus,
} from '../../../shared/api/zoteroClient';
import { getRecentWikiProjects } from '../../../shared/api-client/wiki';
import { useI18n } from '../../../shared/lib/i18n';

type SyncMode = 'incremental' | 'full';

export interface ZoteroSyncPanelProps {
  connected: boolean;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

/** IPC 错误对象上的 HTTP 状态码（`desktopInvoke` 从消息里解析出来）。 */
function errorStatus(error: unknown): number | undefined {
  const code = (error as { status_code?: number } | null)?.status_code;
  return typeof code === 'number' ? code : undefined;
}

/** 409 = 已有同步在跑（后端进程级锁），用友好文案代替裸 FastAPI detail。 */
function isSyncConflict(error: unknown): boolean {
  return errorStatus(error) === 409 || errorMessage(error).includes('already running');
}

/** ISO-8601 字符串 → 本地 `YYYY-MM-DD HH:mm`；无法解析时原样返回。 */
// eslint-disable-next-line react-refresh/only-export-components
export function formatZoteroSyncTime(value: string | null): string | null {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(
    date.getHours(),
  )}:${pad(date.getMinutes())}`;
}

async function resolveProjectPath(boundPath: string): Promise<string | null> {
  if (boundPath) return boundPath;
  const active = useWikiStore.getState().project?.path;
  if (active) return active;
  try {
    const recent = await getRecentWikiProjects();
    return recent[0]?.path ?? null;
  } catch {
    return null;
  }
}

export function ZoteroSyncPanel({ connected }: ZoteroSyncPanelProps) {
  const { t } = useI18n();

  const [status, setStatus] = useState<ZoteroSyncStatus | null>(null);
  const [statusLoading, setStatusLoading] = useState(true);
  const [running, setRunning] = useState<SyncMode | null>(null);
  const [lastResult, setLastResult] = useState<ZoteroSyncResult | null>(null);
  const [lastError, setLastError] = useState<string | null>(null);

  const [wikiTag, setWikiTag] = useState(DEFAULT_WIKI_TAG);
  const [wikiTagSaving, setWikiTagSaving] = useState(false);
  const [wikiTagSaved, setWikiTagSaved] = useState(false);

  const [wikiProjectPath, setWikiProjectPath] = useState('');
  const [savedWikiProjectPath, setSavedWikiProjectPath] = useState('');
  const [wikiProjectSaving, setWikiProjectSaving] = useState(false);
  const [wikiProjectSaved, setWikiProjectSaved] = useState(false);

  // 卸载后不再 setState（React 18 静默丢弃，但避免警告与内存驻留）
  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const loadStatus = useCallback(async () => {
    setStatusLoading(true);
    try {
      setStatus(await zoteroClient.syncStatus());
      setLastError(null);
    } catch (err) {
      setLastError(errorMessage(err));
    } finally {
      setStatusLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadStatus();
  }, [loadStatus]);

  useEffect(() => {
    let cancelled = false;
    void zoteroClient
      .getWikiTag()
      .then((tag) => {
        if (!cancelled) setWikiTag(tag);
      })
      .catch(() => {
        // 读不到就用默认值，不打扰用户
      });
    void zoteroClient
      .getWikiProjectPath()
      .then((path) => {
        if (!cancelled) {
          setWikiProjectPath(path);
          setSavedWikiProjectPath(path);
        }
      })
      .catch(() => {
        // 未绑定是正常状态
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const handleSync = async (force: boolean) => {
    if (running) return;
    setRunning(force ? 'full' : 'incremental');
    setLastError(null);
    setLastResult(null);
    try {
      const projectPath = await resolveProjectPath(savedWikiProjectPath);
      const result = await zoteroClient.sync({ force, projectPath });
      if (!mountedRef.current) return;
      setLastResult(result);
      if (result.skipped) {
        toast.warning(t('settings.zotero.sync.skipped'));
      } else {
        toast.success(t('settings.zotero.sync.done'));
      }
      await loadStatus();
    } catch (err) {
      if (!mountedRef.current) return;
      const message = isSyncConflict(err) ? t('settings.zotero.sync.busy') : errorMessage(err);
      setLastError(message);
      toast.error(`${t('settings.zotero.sync.failed')}: ${message}`);
    } finally {
      if (mountedRef.current) setRunning(null);
    }
  };

  const handleSaveWikiTag = async () => {
    setWikiTagSaving(true);
    setWikiTagSaved(false);
    try {
      await zoteroClient.setWikiTag(wikiTag);
      if (!mountedRef.current) return;
      setWikiTag(wikiTag.trim() || DEFAULT_WIKI_TAG);
      setWikiTagSaved(true);
      setLastError(null);
    } catch (err) {
      if (!mountedRef.current) return;
      setLastError(errorMessage(err));
    } finally {
      if (mountedRef.current) setWikiTagSaving(false);
    }
  };

  const handleSaveWikiProject = async () => {
    setWikiProjectSaving(true);
    setWikiProjectSaved(false);
    try {
      await zoteroClient.setWikiProjectPath(wikiProjectPath);
      if (!mountedRef.current) return;
      setWikiProjectPath(wikiProjectPath.trim());
      setSavedWikiProjectPath(wikiProjectPath.trim());
      setWikiProjectSaved(true);
      setLastError(null);
      await loadStatus();
    } catch (err) {
      if (!mountedRef.current) return;
      setLastError(errorMessage(err));
    } finally {
      if (mountedRef.current) setWikiProjectSaving(false);
    }
  };

  const busy = running !== null || (status?.sync_in_progress ?? false);
  const embeddingMissing = status?.embedding_configured === false;
  const lastSyncAt = formatZoteroSyncTime(status?.last_sync_at ?? null);
  const wikiOnlyHint = lastResult != null && lastResult.wiki == null;

  return (
    <div className="rounded-lg border border-line-subtle bg-surface-raised p-4 space-y-3">
      <div>
        <h4 className="text-sm font-medium text-primary">{t('settings.zotero.sync.title')}</h4>
        <p className="mt-1 text-xs text-faint">{t('settings.zotero.sync.desc')}</p>
      </div>

      {/* Status line */}
      {statusLoading && !status ? (
        <p className="text-xs text-faint">…</p>
      ) : status ? (
        <p data-testid="zotero-sync-status-line" className="text-xs text-secondary">
          {t('settings.zotero.sync.indexed')}{' '}
          <span className="font-semibold text-primary">{status.item_count}</span>
          {' · '}
          {t('settings.zotero.sync.wiki_pages')}{' '}
          <span className="font-semibold text-primary">{status.wiki_page_count}</span>
          {' · '}
          {t('settings.zotero.sync.last_sync')}{' '}
          <span className="text-primary">{lastSyncAt ?? t('settings.zotero.sync.never')}</span>
        </p>
      ) : null}

      {embeddingMissing && (
        <p data-testid="zotero-sync-embedding-hint" className="text-xs text-amber-400">
          {t('settings.zotero.sync.embedding_missing')}
        </p>
      )}

      {/* Actions */}
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          data-testid="zotero-sync-now"
          className="rounded bg-accent px-3 py-1.5 text-sm font-medium text-white hover:opacity-90 disabled:opacity-50"
          disabled={!connected || busy}
          onClick={() => void handleSync(false)}
        >
          {running === 'incremental'
            ? t('settings.zotero.sync.syncing')
            : t('settings.zotero.sync.sync_now')}
        </button>
        <button
          type="button"
          data-testid="zotero-sync-rebuild"
          className="rounded border border-line-subtle bg-surface px-3 py-1.5 text-sm text-secondary hover:text-primary disabled:opacity-50"
          disabled={!connected || busy}
          onClick={() => void handleSync(true)}
        >
          {running === 'full'
            ? t('settings.zotero.sync.syncing')
            : t('settings.zotero.sync.rebuild')}
        </button>
        {busy && <span className="text-xs text-faint">{t('settings.zotero.sync.syncing')}</span>}
      </div>
      <p className="text-xs text-faint">{t('settings.zotero.sync.rebuild_hint')}</p>

      {/* Last result */}
      {lastResult && (
        <div data-testid="zotero-sync-result" className="text-xs text-secondary space-y-0.5">
          <p>
            {lastResult.skipped
              ? t('settings.zotero.sync.skipped')
              : t('settings.zotero.sync.done')}
            {!lastResult.skipped && (
              <>
                {' · '}
                {t('settings.zotero.sync.indexed')}: {lastResult.items}
                {' · '}
                {(lastResult.elapsed_ms / 1000).toFixed(1)}s
              </>
            )}
          </p>
          {lastResult.wiki && !('error' in lastResult.wiki) && (
            <p>
              {t('settings.zotero.sync.wiki_exported')}: {lastResult.wiki.items_exported ?? 0}{' '}
              {t('settings.zotero.stats.items')} · {lastResult.wiki.authors_exported ?? 0}{' '}
              {t('settings.zotero.sync.wiki_authors')}
            </p>
          )}
          {wikiOnlyHint && (
            <p data-testid="zotero-sync-project-hint" className="text-faint">
              {t('settings.zotero.sync.project_missing')}
            </p>
          )}
          {lastResult.wiki && 'error' in lastResult.wiki && lastResult.wiki.error && (
            <p className="text-red-400">
              {t('settings.zotero.sync.wiki_exported')}: {lastResult.wiki.error}
            </p>
          )}
          {lastResult.errors.length > 0 && (
            <div className="text-red-400">
              <p>
                {t('settings.zotero.sync.error_count')} ({lastResult.errors.length})
              </p>
              <ul className="list-disc pl-4">
                {lastResult.errors.slice(0, 5).map((err) => (
                  <li key={err} className="line-clamp-2">
                    {err}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      {lastError && (
        <p data-testid="zotero-sync-error" className="text-xs text-red-400">
          {lastError}
        </p>
      )}

      {/* Wiki tag config */}
      <div className="border-t border-line-subtle pt-3">
        <label className="mb-1 block text-xs font-medium text-secondary" htmlFor="zotero-wiki-tag">
          {t('settings.zotero.wiki_tag.label')}
        </label>
        <div className="flex gap-2">
          <input
            id="zotero-wiki-tag"
            type="text"
            className="flex-1 rounded border border-line-subtle bg-surface px-3 py-1.5 text-sm text-primary placeholder:text-faint/60 focus:border-accent focus:outline-none"
            placeholder={DEFAULT_WIKI_TAG}
            value={wikiTag}
            onChange={(e) => {
              setWikiTag(e.target.value);
              setWikiTagSaved(false);
            }}
          />
          <button
            type="button"
            className="rounded bg-accent px-3 py-1.5 text-sm font-medium text-white hover:opacity-90 disabled:opacity-50"
            disabled={wikiTagSaving}
            onClick={() => void handleSaveWikiTag()}
          >
            {wikiTagSaving ? '…' : t('settings.zotero.wiki_tag.save')}
          </button>
        </div>
        <p className="mt-1 text-xs text-faint">{t('settings.zotero.wiki_tag.hint')}</p>
        {wikiTagSaved && (
          <p className="mt-1 text-xs text-green-400">{t('settings.zotero.wiki_tag.saved')}</p>
        )}
      </div>

      {/* Wiki project binding */}
      <div className="border-t border-line-subtle pt-3">
        <label
          className="mb-1 block text-xs font-medium text-secondary"
          htmlFor="zotero-wiki-project"
        >
          {t('settings.zotero.wiki_project.label')}
        </label>
        <div className="flex gap-2">
          <input
            id="zotero-wiki-project"
            data-testid="zotero-wiki-project-input"
            type="text"
            className="flex-1 rounded border border-line-subtle bg-surface px-3 py-1.5 text-sm text-primary placeholder:text-faint/60 focus:border-accent focus:outline-none"
            placeholder={t('settings.zotero.wiki_project.placeholder')}
            value={wikiProjectPath}
            onChange={(e) => {
              setWikiProjectPath(e.target.value);
              setWikiProjectSaved(false);
            }}
          />
          <button
            type="button"
            data-testid="zotero-wiki-project-save"
            className="rounded bg-accent px-3 py-1.5 text-sm font-medium text-white hover:opacity-90 disabled:opacity-50"
            disabled={wikiProjectSaving}
            onClick={() => void handleSaveWikiProject()}
          >
            {wikiProjectSaving ? '…' : t('settings.zotero.wiki_project.save')}
          </button>
        </div>
        <p className="mt-1 text-xs text-faint">{t('settings.zotero.wiki_project.hint')}</p>
        {wikiProjectSaved && (
          <p className="mt-1 text-xs text-green-400">{t('settings.zotero.wiki_project.saved')}</p>
        )}
      </div>
    </div>
  );
}
