/**
 * ModelCatalog 页面 (Task 6, 2026-09-15)
 *
 * 路由: /model-catalog
 *
 * 三栏布局:
 * - 顶部工具栏: 搜索框 + 端点选择 + 同步/导入/导出按钮 + 快照列表下拉
 * - 左: CatalogTable (catalog 源视图, 支持过滤)
 * - 右: ModelDetails (选中行的 effective + override + 探测)
 * - 底部抽屉: SnapshotReview (快照审核, 通过 /review?snapshot=<id> 激活)
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';

import {
  exportSnapshot,
  importSnapshot,
  listModels,
  listSnapshots,
  syncOpenRouter,
} from '../entities/model-catalog/api';
import type { CandidateModel, SnapshotMeta } from '../entities/model-catalog/types';
import { useSettings } from '../features/manage-settings/useSettings';
import {
  CatalogTable,
  ModelDetails,
  SnapshotReview,
  catalogItemKey,
} from '../widgets/model-catalog';

export default function ModelCatalog() {
  const [searchParams, setSearchParams] = useSearchParams();
  const activeSnapshot = searchParams.get('snapshot');

  const [allItems, setAllItems] = useState<CandidateModel[]>([]);
  const [filteredItems, setFilteredItems] = useState<CandidateModel[]>([]);
  const [snapshots, setSnapshots] = useState<SnapshotMeta[]>([]);
  const { settings } = useSettings();
  const [searchTerm, setSearchTerm] = useState('');
  const [endpointId, setEndpointId] = useState('');
  const [selected, setSelected] = useState<CandidateModel | null>(null);
  const [loading, setLoading] = useState(false);
  const [pageError, setPageError] = useState<string | null>(null);
  const [pageStatus, setPageStatus] = useState<string | null>(null);
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const reloadGeneration = useRef(0);
  const endpointIdRef = useRef(endpointId);
  endpointIdRef.current = endpointId;

  const reload = useCallback(async () => {
    if (endpointIdRef.current !== endpointId) return;
    const generation = ++reloadGeneration.current;
    setLoading(true);
    setPageError(null);
    try {
      const [list, snaps] = await Promise.all([
        listModels({
          // 后端硬上限 100; 调用方与后端契约一致, 不发送无效请求
          limit: 100,
          offset: 0,
          endpointId: endpointId || undefined,
        }),
        listSnapshots(),
      ]);
      if (generation !== reloadGeneration.current) return;
      setAllItems(list.items);
      setSelected((current) => {
        if (!current) return null;
        const currentKey = catalogItemKey(current);
        return list.items.find((item) => catalogItemKey(item) === currentKey) ?? null;
      });
      setSnapshots(snaps);
    } catch (err) {
      if (generation !== reloadGeneration.current) return;
      setPageError(err instanceof Error ? err.message : String(err));
      setAllItems([]);
      setSnapshots([]);
    } finally {
      if (generation === reloadGeneration.current) setLoading(false);
    }
  }, [endpointId]);

  useEffect(() => {
    void reload();
  }, [reload]);

  // 客户端过滤 — 大小写不敏感, 匹配 model_id / provider
  useEffect(() => {
    const q = searchTerm.trim().toLowerCase();
    if (!q) {
      setFilteredItems(allItems);
      return;
    }
    setFilteredItems(
      allItems.filter((item) => {
        const id = `${item.model_key.provider}/${item.model_key.model_id}`.toLowerCase();
        return id.includes(q);
      }),
    );
  }, [searchTerm, allItems]);

  const selectedKey = useMemo(() => (selected ? catalogItemKey(selected) : null), [selected]);

  async function handleSync(): Promise<void> {
    setBusyAction('sync');
    setPageError(null);
    setPageStatus(null);
    try {
      const result = await syncOpenRouter();
      setPageStatus(
        result.snapshot_id
          ? `同步成功, 快照 ${result.snapshot_id} (${result.count} 项)`
          : `同步完成, 无新数据 (${result.count} 项)`,
      );
      await reload();
    } catch (err) {
      setPageError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusyAction(null);
    }
  }

  async function handleImport(): Promise<void> {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = 'application/json';
    input.onchange = async () => {
      const file = input.files?.[0];
      if (!file) return;
      setBusyAction('import');
      setPageError(null);
      setPageStatus(null);
      try {
        const text = await file.text();
        const body = JSON.parse(text);
        const result = await importSnapshot(body);
        setPageStatus(`导入成功, 快照 ${result.snapshot_id} (${result.count} 项)`);
        await reload();
      } catch (err) {
        setPageError(err instanceof Error ? err.message : String(err));
      } finally {
        setBusyAction(null);
      }
    };
    input.click();
  }

  async function handleExport(): Promise<void> {
    const id = activeSnapshot;
    if (!id) {
      setPageError('请先选择一个快照');
      return;
    }
    setBusyAction('export');
    setPageError(null);
    setPageStatus(null);
    try {
      const blob = await exportSnapshot(id);
      const text = JSON.stringify(blob, null, 2);
      const url = URL.createObjectURL(new Blob([text], { type: 'application/json' }));
      const a = document.createElement('a');
      a.href = url;
      a.download = `${id}.json`;
      a.click();
      URL.revokeObjectURL(url);
      setPageStatus(`已导出 ${id}`);
    } catch (err) {
      setPageError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusyAction(null);
    }
  }

  function openReview(id: string): void {
    setSearchParams({ snapshot: id }, { replace: true });
  }

  function closeReview(): void {
    setSearchParams({}, { replace: true });
    void reload();
  }

  return (
    <div className="flex flex-1 overflow-hidden">
      <div className="flex-1 flex flex-col overflow-hidden">
        <div
          className="h-12 flex items-center px-5 border-b border-border bg-surface flex-shrink-0 gap-3"
          data-testid="model-catalog-header"
        >
          <h2 className="text-[18px] font-semibold text-text">模型目录</h2>
          <input
            type="search"
            placeholder="搜索模型 (按 model_id / provider)"
            data-testid="model-catalog-search"
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="ml-4 px-2 py-1 text-xs border border-border rounded bg-bg w-64"
          />
          <label className="text-xs text-text-muted">
            端点:
            <select
              data-testid="model-catalog-endpoint"
              value={endpointId}
              onChange={(e) => {
                setEndpointId(e.target.value);
                setSelected(null);
              }}
              className="ml-1 px-2 py-1 text-xs border border-border rounded bg-bg"
            >
              <option value="">全部</option>
              {settings.endpoints.map((endpoint) => (
                <option key={endpoint.id} value={endpoint.id}>
                  {endpoint.name || endpoint.id}
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            data-testid="model-catalog-sync"
            onClick={() => void handleSync()}
            disabled={busyAction !== null}
            className="px-2 py-1 text-xs border border-border rounded hover:bg-bg-hover disabled:opacity-50"
          >
            {busyAction === 'sync' ? '同步中…' : '同步 OpenRouter'}
          </button>
          <button
            type="button"
            data-testid="model-catalog-import"
            onClick={() => void handleImport()}
            disabled={busyAction !== null}
            className="px-2 py-1 text-xs border border-border rounded hover:bg-bg-hover disabled:opacity-50"
          >
            导入快照
          </button>
          <button
            type="button"
            data-testid="model-catalog-export"
            onClick={() => void handleExport()}
            disabled={busyAction !== null || !activeSnapshot}
            className="px-2 py-1 text-xs border border-border rounded hover:bg-bg-hover disabled:opacity-50"
          >
            {busyAction === 'export' ? '导出中…' : '导出当前快照'}
          </button>
          {pageStatus && (
            <span
              className="text-xs text-text-muted"
              data-testid="model-catalog-status"
              role="status"
              aria-live="polite"
            >
              <span aria-hidden="true">ℹ️</span> {pageStatus}
            </span>
          )}
        </div>

        {pageError && (
          <div
            className="mx-5 mt-2 text-xs px-2 py-1 border border-border rounded"
            role="alert"
            aria-live="polite"
            data-testid="model-catalog-error"
          >
            <span aria-hidden="true">⚠️</span> {pageError}
          </div>
        )}

        <div className="flex-1 flex overflow-hidden">
          <div className="flex-1 p-5 overflow-auto">
            <CatalogTable
              items={filteredItems}
              selectedKey={selectedKey}
              onSelect={(item) => {
                setSelected(item);
              }}
              loading={loading}
            />
          </div>
          <div className="w-96 border-l border-border p-4 overflow-auto bg-surface">
            <ModelDetails
              item={selected}
              endpointId={endpointId}
              onStatusChange={setPageStatus}
              onReload={reload}
            />
          </div>
        </div>

        {snapshots.length > 0 && (
          <div
            className="border-t border-border bg-surface px-5 py-2 flex items-center gap-2"
            data-testid="model-catalog-snapshots"
          >
            <span className="text-xs text-text-muted">快照:</span>
            {snapshots.map((snap) => {
              const isActive = snap.id === activeSnapshot;
              return (
                <button
                  key={snap.id}
                  type="button"
                  data-testid={`model-catalog-snapshot-${snap.id}`}
                  onClick={() => (isActive ? closeReview() : openReview(snap.id))}
                  className={`px-2 py-1 text-xs border border-border rounded ${
                    isActive ? 'bg-accent-soft' : 'hover:bg-bg-hover'
                  }`}
                >
                  {snap.id} · {snap.source} · {snap.digest.slice(0, 8)}
                </button>
              );
            })}
          </div>
        )}
      </div>

      {activeSnapshot && (
        <aside
          className="w-[480px] border-l border-border bg-bg overflow-auto"
          data-testid="model-catalog-review"
        >
          <div className="sticky top-0 bg-bg border-b border-border px-4 py-2 flex items-center justify-between">
            <h3 className="text-sm font-semibold">快照审核</h3>
            <button
              type="button"
              data-testid="model-catalog-review-close"
              onClick={closeReview}
              aria-label="关闭审核"
              className="text-xs px-2 py-1 border border-border rounded hover:bg-bg-hover"
            >
              关闭 (Esc)
            </button>
          </div>
          <SnapshotReview snapshotId={activeSnapshot} onClose={closeReview} />
        </aside>
      )}
    </div>
  );
}
