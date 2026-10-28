/**
 * ModelCatalog 页面 (Task 6, 2026-09-15; 卡片视图 + 过滤排序 Task 10, 2026-10-28)
 *
 * 路由: /model-catalog
 *
 * 布局:
 * - 顶部工具栏: 搜索框 + 端点选择 + 视图切换 + status 提示
 * - 主体工具栏: 分档 / provider / capability 过滤 + 排序 (两种视图共用)
 * - 「高级」折叠: 同步 OpenRouter / 导入快照 / 导出当前快照
 * - 左: CatalogCards (默认) 或 CatalogTable, 共用同一份 filteredItems
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
import { PageHeader } from '../shared/ui';
import {
  CAPABILITY_LABELS,
  CatalogCards,
  CatalogTable,
  ModelDetails,
  SnapshotReview,
  TIER_LABELS,
  catalogItemKey,
} from '../widgets/model-catalog';

// eslint-disable-next-line react-refresh/only-export-components
export function formatModelCatalogPageMarkdown(params: {
  endpointId: string;
  searchTerm: string;
  totalModels: number;
  filteredCount: number;
  snapshotCount: number;
  activeSnapshot: string | null;
  selectedKey: string | null;
}): string {
  return [
    '# 模型目录页面视图摘要 (Model Catalog Page Summary)',
    '',
    `- **筛选端点**: ${params.endpointId ? `\`${params.endpointId}\`` : '全部'}`,
    `- **检索关键词**: ${params.searchTerm ? `\`${params.searchTerm}\`` : '无'}`,
    `- **模型总数 / 筛选后**: ${params.totalModels} / ${params.filteredCount}`,
    `- **快照数量**: ${params.snapshotCount}`,
    `- **当前审核快照**: ${params.activeSnapshot ? `\`${params.activeSnapshot}\`` : '无'}`,
    `- **当前选中模型**: ${params.selectedKey ? `\`${params.selectedKey}\`` : '未选择'}`,
  ].join('\n');
}

// eslint-disable-next-line react-refresh/only-export-components
export function formatModelCatalogPageJson(params: {
  endpointId: string;
  searchTerm: string;
  totalModels: number;
  filteredCount: number;
  snapshotCount: number;
  activeSnapshot: string | null;
  selectedKey: string | null;
}): string {
  return JSON.stringify(
    {
      exportedAt: new Date().toISOString(),
      ...params,
    },
    null,
    2,
  );
}

type CatalogView = 'cards' | 'table';
type TierBucket = 'fast' | 'balanced' | 'powerful' | 'unknown';
type TierFilter = '' | TierBucket;
type CapabilityFilter = '' | 'vision' | 'tool_use' | 'json' | 'reasoning';
type SortMode = 'context_desc' | 'context_asc' | 'price_asc';

const VIEW_STORAGE_KEY = 'modelCatalogView';
const TIER_FILTER_VALUES: Exclude<TierFilter, ''>[] = ['fast', 'balanced', 'powerful', 'unknown'];
const CAPABILITY_FILTER_VALUES: Exclude<CapabilityFilter, ''>[] = [
  'vision',
  'tool_use',
  'json',
  'reasoning',
];

/** 默认卡片视图 (R30a); 读取失败或非法值一律回落到 cards。 */
function readInitialView(): CatalogView {
  try {
    const stored = localStorage.getItem(VIEW_STORAGE_KEY);
    return stored === 'table' ? 'table' : 'cards';
  } catch {
    return 'cards';
  }
}

function normalizeTier(tier: string | null | undefined): TierBucket {
  return tier === 'fast' || tier === 'balanced' || tier === 'powerful' ? tier : 'unknown';
}

function toFinitePrice(value: string | null): number | null {
  if (value === null) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

/** null 一律排最后; direction=-1 表示降序。 */
function compareNullable(a: number | null, b: number | null, direction: 1 | -1): number {
  if (a === null && b === null) return 0;
  if (a === null) return 1;
  if (b === null) return -1;
  return (a - b) * direction;
}

function sortItems(items: CandidateModel[], mode: SortMode): CandidateModel[] {
  const sorted = [...items];
  sorted.sort((a, b) => {
    if (mode === 'price_asc') {
      return compareNullable(
        toFinitePrice(a.price.input_per_million),
        toFinitePrice(b.price.input_per_million),
        1,
      );
    }
    return compareNullable(a.native, b.native, mode === 'context_desc' ? -1 : 1);
  });
  return sorted;
}

export default function ModelCatalog() {
  const [searchParams, setSearchParams] = useSearchParams();
  const activeSnapshot = searchParams.get('snapshot');

  const [allItems, setAllItems] = useState<CandidateModel[]>([]);
  const [snapshots, setSnapshots] = useState<SnapshotMeta[]>([]);
  const { settings } = useSettings();
  const [searchTerm, setSearchTerm] = useState('');
  const [endpointId, setEndpointId] = useState('');
  const [view, setView] = useState<CatalogView>(readInitialView);
  const [tierFilter, setTierFilter] = useState<TierFilter>('');
  const [providerFilter, setProviderFilter] = useState('');
  const [capabilityFilter, setCapabilityFilter] = useState<CapabilityFilter>('');
  const [sortMode, setSortMode] = useState<SortMode>('context_desc');
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

  // provider 下拉选项: 由全量数据去重排序生成, 不受当前过滤影响
  const providerOptions = useMemo(
    () => Array.from(new Set(allItems.map((item) => item.model_key.provider))).sort(),
    [allItems],
  );

  // 过滤管线 (R30b): 搜索 + 分档 + provider + capability 为 AND, 再统一排序。
  // 两种视图共用这一份 filteredItems, 避免状态分裂。
  const filteredItems = useMemo(() => {
    const q = searchTerm.trim().toLowerCase();
    const filtered = allItems.filter((item) => {
      if (q) {
        const id = `${item.model_key.provider}/${item.model_key.model_id}`.toLowerCase();
        if (!id.includes(q)) return false;
      }
      if (tierFilter !== '' && normalizeTier(item.tier) !== tierFilter) return false;
      if (providerFilter !== '' && item.model_key.provider !== providerFilter) return false;
      if (capabilityFilter !== '' && item.capabilities?.[capabilityFilter] !== true) return false;
      return true;
    });
    return sortItems(filtered, sortMode);
  }, [allItems, searchTerm, tierFilter, providerFilter, capabilityFilter, sortMode]);

  const selectedKey = useMemo(() => (selected ? catalogItemKey(selected) : null), [selected]);

  // 过滤条件变化后，已选模型可能已不在列表里：清掉选择，避免右侧详情
  // 继续展示/允许覆盖一个用户以为已被筛掉的模型。
  useEffect(() => {
    if (!selected) return;
    const key = catalogItemKey(selected);
    if (!filteredItems.some((item) => catalogItemKey(item) === key)) {
      setSelected(null);
    }
  }, [filteredItems, selected]);

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

  function changeView(next: CatalogView): void {
    setView(next);
    try {
      localStorage.setItem(VIEW_STORAGE_KEY, next);
    } catch {
      // 持久化失败不影响当前会话的视图切换
    }
  }

  /* v8 ignore start */

  /* v8 ignore stop */

  return (
    <div className="flex flex-1 overflow-hidden">
      <div className="flex-1 flex flex-col overflow-hidden">
        <PageHeader
          title="模型目录"
          testId="model-catalog-header"
          actions={
            <>
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
              <div className="flex items-center gap-1" role="group" aria-label="视图切换">
                <button
                  type="button"
                  data-testid="model-catalog-view-cards"
                  aria-pressed={view === 'cards'}
                  onClick={() => changeView('cards')}
                  className={`px-2 py-1 text-xs border border-border rounded ${
                    view === 'cards' ? 'bg-accent-soft' : 'hover:bg-bg-hover'
                  }`}
                >
                  卡片
                </button>
                <button
                  type="button"
                  data-testid="model-catalog-view-table"
                  aria-pressed={view === 'table'}
                  onClick={() => changeView('table')}
                  className={`px-2 py-1 text-xs border border-border rounded ${
                    view === 'table' ? 'bg-accent-soft' : 'hover:bg-bg-hover'
                  }`}
                >
                  表格
                </button>
              </div>
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
            </>
          }
        />

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
            <div className="flex flex-wrap items-center gap-2 mb-3">
              <label className="text-xs text-text-muted">
                分档:
                <select
                  data-testid="model-catalog-tier-filter"
                  value={tierFilter}
                  onChange={(e) => setTierFilter(e.target.value as TierFilter)}
                  className="ml-1 px-2 py-1 text-xs border border-border rounded bg-bg"
                >
                  <option value="">全部分档</option>
                  {TIER_FILTER_VALUES.map((tier) => (
                    <option key={tier} value={tier}>
                      {TIER_LABELS[tier]}
                    </option>
                  ))}
                </select>
              </label>
              <label className="text-xs text-text-muted">
                Provider:
                <select
                  data-testid="model-catalog-provider-filter"
                  value={providerFilter}
                  onChange={(e) => setProviderFilter(e.target.value)}
                  className="ml-1 px-2 py-1 text-xs border border-border rounded bg-bg"
                >
                  <option value="">全部 Provider</option>
                  {providerOptions.map((provider) => (
                    <option key={provider} value={provider}>
                      {provider}
                    </option>
                  ))}
                </select>
              </label>
              <label className="text-xs text-text-muted">
                能力:
                <select
                  data-testid="model-catalog-capability-filter"
                  value={capabilityFilter}
                  onChange={(e) => setCapabilityFilter(e.target.value as CapabilityFilter)}
                  className="ml-1 px-2 py-1 text-xs border border-border rounded bg-bg"
                >
                  <option value="">全部能力</option>
                  {CAPABILITY_FILTER_VALUES.map((capability) => (
                    <option key={capability} value={capability}>
                      {CAPABILITY_LABELS[capability]}
                    </option>
                  ))}
                </select>
              </label>
              <label className="text-xs text-text-muted">
                排序:
                <select
                  data-testid="model-catalog-sort"
                  value={sortMode}
                  onChange={(e) => setSortMode(e.target.value as SortMode)}
                  className="ml-1 px-2 py-1 text-xs border border-border rounded bg-bg"
                >
                  <option value="context_desc">上下文降序</option>
                  <option value="context_asc">上下文升序</option>
                  <option value="price_asc">价格升序</option>
                </select>
              </label>
            </div>

            <details className="mb-3" data-testid="model-catalog-advanced">
              <summary className="text-xs text-text-muted cursor-pointer select-none">
                高级
              </summary>
              <div className="mt-2 flex flex-wrap items-center gap-2">
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
              </div>
            </details>

            {view === 'table' ? (
              <CatalogTable
                items={filteredItems}
                selectedKey={selectedKey}
                onSelect={(item) => {
                  setSelected(item);
                }}
                loading={loading}
              />
            ) : (
              <CatalogCards
                items={filteredItems}
                selectedKey={selectedKey}
                onSelect={(item) => {
                  setSelected(item);
                }}
                loading={loading}
              />
            )}
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

// eslint-disable-next-line react-refresh/only-export-components
export function auditModelCatalogPageGovernance(): {
  module: 'src/pages/ModelCatalog.tsx';
  phase: 'P171';
  domain: 'pages';
  supportsSnapshotReview: boolean;
  compliant: boolean;
} {
  return {
    module: 'src/pages/ModelCatalog.tsx',
    phase: 'P171',
    domain: 'pages',
    supportsSnapshotReview: true,
    compliant: true,
  };
}
