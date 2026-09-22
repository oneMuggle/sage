/**
 * Settings 页面 - Zotero 文献库 Tab
 *
 * 只读访问本地 Zotero 文献库。提供:
 * - 连接状态 + 库统计卡片
 * - 自定义 DB 路径配置(保存后刷新状态)
 * - 搜索框(防抖 300ms,可验证连通性)
 * - 搜索结果列表(点击展开详情)
 */
import { useCallback, useEffect, useRef, useState } from 'react';

import {
  zoteroClient,
  type ZoteroItemDetail,
  type ZoteroItemSummary,
  type ZoteroStatus,
} from '../../shared/api/zoteroClient';
import { useI18n } from '../../shared/lib/i18n';

const DEBOUNCE_MS = 300;

export function ZoteroTab() {
  const { t } = useI18n();

  // ── status ──────────────────────────────────────────────────────────────────
  const [status, setStatus] = useState<ZoteroStatus | null>(null);
  const [statusLoading, setStatusLoading] = useState(true);

  // ── path config ─────────────────────────────────────────────────────────────
  const [pathInput, setPathInput] = useState('');
  const [pathSaving, setPathSaving] = useState(false);
  const [pathSaved, setPathSaved] = useState(false);

  // ── search ───────────────────────────────────────────────────────────────────
  const [query, setQuery] = useState('');
  const [searchResults, setSearchResults] = useState<ZoteroItemSummary[]>([]);
  const [searchLoading, setSearchLoading] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [selectedItem, setSelectedItem] = useState<ZoteroItemDetail | null>(null);
  const [itemLoading, setItemLoading] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // ── load status on mount ─────────────────────────────────────────────────────
  const loadStatus = useCallback(async () => {
    setStatusLoading(true);
    try {
      const s = await zoteroClient.status();
      setStatus(s);
      if (s.db_path) setPathInput(s.db_path);
    } catch {
      setStatus({
        available: false,
        db_path: null,
        error: t('settings.zotero.error.generic'),
        stats: null,
      });
    } finally {
      setStatusLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void loadStatus();
  }, [loadStatus]);

  // ── save path ────────────────────────────────────────────────────────────────
  const handleSavePath = async () => {
    setPathSaving(true);
    setPathSaved(false);
    try {
      await zoteroClient.setPath(pathInput.trim());
      setPathSaved(true);
      await loadStatus();
    } catch {
      // status will reflect failure on next load
    } finally {
      setPathSaving(false);
    }
  };

  // ── search (debounced) ───────────────────────────────────────────────────────
  useEffect(() => {
    if (!status?.available) return;
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(async () => {
      if (!query.trim()) {
        setSearchResults([]);
        setSearchError(null);
        return;
      }
      setSearchLoading(true);
      setSearchError(null);
      try {
        const results = await zoteroClient.search({ q: query, limit: 30 });
        setSearchResults(results);
      } catch (err) {
        setSearchError(err instanceof Error ? err.message : t('settings.zotero.error.generic'));
        setSearchResults([]);
      } finally {
        setSearchLoading(false);
      }
    }, DEBOUNCE_MS);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [query, status?.available, t]);

  // ── item detail ──────────────────────────────────────────────────────────────
  const handleSelectItem = async (key: string) => {
    if (selectedItem?.key === key) {
      setSelectedItem(null);
      return;
    }
    setItemLoading(true);
    try {
      const detail = await zoteroClient.getItem(key);
      setSelectedItem(detail);
    } catch {
      setSelectedItem(null);
    } finally {
      setItemLoading(false);
    }
  };

  // ── render ───────────────────────────────────────────────────────────────────
  const connected = status?.available ?? false;

  return (
    <div className="space-y-5">
      {/* Header */}
      <div>
        <h3 className="text-sm font-medium text-primary">{t('settings.zotero.title')}</h3>
        <p className="mt-1 text-xs text-faint">{t('settings.zotero.desc')}</p>
      </div>

      {/* Status card */}
      <div className="rounded-lg border border-line-subtle bg-surface-raised p-4">
        <div className="flex items-center gap-2">
          <span
            className={`inline-block h-2 w-2 rounded-full ${
              connected
                ? 'bg-green-500'
                : statusLoading
                  ? 'bg-amber-400 animate-pulse'
                  : 'bg-faint'
            }`}
          />
          <span className="text-sm text-primary">
            {statusLoading
              ? t('settings.zotero.status.checking')
              : connected
                ? t('settings.zotero.status.connected')
                : t('settings.zotero.status.disconnected')}
          </span>
        </div>

        {connected && status?.stats && (
          <div className="mt-3 grid grid-cols-4 gap-3 text-center">
            {(
              [
                { label: t('settings.zotero.stats.items'), value: status.stats.items },
                { label: t('settings.zotero.stats.collections'), value: status.stats.collections },
                { label: t('settings.zotero.stats.tags'), value: status.stats.tags },
                { label: t('settings.zotero.stats.attachments'), value: status.stats.attachments },
              ] as const
            ).map(({ label, value }) => (
              <div key={label} className="rounded border border-line-subtle bg-surface px-2 py-2">
                <div className="text-base font-semibold text-primary">{value.toLocaleString()}</div>
                <div className="text-xs text-faint">{label}</div>
              </div>
            ))}
          </div>
        )}

        {!connected && !statusLoading && (
          <p className="mt-2 text-xs text-red-400">
            {status?.error ?? t('settings.zotero.error.unavailable')}
          </p>
        )}
      </div>

      {/* Path config */}
      <div>
        <label className="mb-1 block text-xs font-medium text-secondary" htmlFor="zotero-path">
          {t('settings.zotero.path.label')}
        </label>
        <div className="flex gap-2">
          <input
            id="zotero-path"
            type="text"
            className="flex-1 rounded border border-line-subtle bg-surface px-3 py-1.5 text-sm text-primary placeholder:text-faint/60 focus:border-accent focus:outline-none"
            placeholder={t('settings.zotero.path.placeholder')}
            value={pathInput}
            onChange={(e) => {
              setPathInput(e.target.value);
              setPathSaved(false);
            }}
          />
          <button
            type="button"
            className="rounded bg-accent px-3 py-1.5 text-sm font-medium text-white hover:opacity-90 disabled:opacity-50"
            disabled={pathSaving}
            onClick={handleSavePath}
          >
            {pathSaving ? '…' : t('settings.zotero.path.save')}
          </button>
        </div>
        {pathSaved && <p className="mt-1 text-xs text-green-400">{t('settings.zotero.path.saved')}</p>}
      </div>

      {/* Search + results (only when connected) */}
      {connected && (
        <>
          <div>
            <input
              type="text"
              className="w-full rounded border border-line-subtle bg-surface px-3 py-1.5 text-sm text-primary placeholder:text-faint/60 focus:border-accent focus:outline-none"
              placeholder={t('settings.zotero.search.placeholder')}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
            {searchError && <p className="mt-1 text-xs text-red-400">{searchError}</p>}
          </div>

          {searchResults.length > 0 && (
            <div className="space-y-1">
              {searchResults.map((item) => (
                <button
                  key={item.key}
                  type="button"
                  className="w-full rounded border border-line-subtle bg-surface-raised px-3 py-2 text-left hover:border-accent/50 transition-colors"
                  onClick={() => handleSelectItem(item.key)}
                >
                  <div className="text-sm text-primary line-clamp-1">{item.title}</div>
                  <div className="mt-0.5 flex gap-2 text-xs text-faint">
                    {item.authors.length > 0 && <span>{item.authors.slice(0, 3).join(', ')}</span>}
                    {item.year != null && <span>({item.year})</span>}
                    <span className="capitalize">{item.item_type}</span>
                  </div>
                  {selectedItem?.key === item.key && (
                    <div className="mt-2 border-t border-line-subtle pt-2 text-xs text-secondary space-y-1">
                      {itemLoading ? (
                        <p className="text-faint">…</p>
                      ) : (
                        <>
                          {selectedItem.abstract && (
                            <p className="line-clamp-3 text-faint">{selectedItem.abstract}</p>
                          )}
                          {selectedItem.tags.length > 0 && (
                            <div className="flex flex-wrap gap-1">
                              {selectedItem.tags.map((tag) => (
                                <span
                                  key={tag}
                                  className="rounded bg-accent/15 px-1.5 py-0.5 text-accent"
                                >
                                  {tag}
                                </span>
                              ))}
                            </div>
                          )}
                          {selectedItem.attachments.length > 0 && (
                            <p className="text-faint">
                              📎 {selectedItem.attachments.length}{' '}
                              {t('settings.zotero.stats.attachments').toLowerCase()}
                            </p>
                          )}
                          {selectedItem.doi && (
                            <p className="text-accent truncate">DOI: {selectedItem.doi}</p>
                          )}
                        </>
                      )}
                    </div>
                  )}
                </button>
              ))}
            </div>
          )}

          {query.trim() && !searchLoading && searchResults.length === 0 && !searchError && (
            <p className="text-center text-xs text-faint">{t('settings.zotero.search.empty')}</p>
          )}
        </>
      )}
    </div>
  );
}
