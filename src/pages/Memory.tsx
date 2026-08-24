import { Plus, Download } from 'lucide-react';
import { useState } from 'react';

import { memoryApi } from '../shared/api';
import type { Memory } from '../shared/api/types';
import { ErrorState } from '../shared/ui/ErrorState';
import { MemoryBrowser, NewMemoryModal } from '../widgets/memory';

const MEMORY_EXPORT_PAGE_SIZE = 100;
const MEMORY_EXPORT_MAX_ITEMS = 1000;

export function Memory() {
  const [showNewMemory, setShowNewMemory] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);
  // Bump after a successful save to refresh the MemoryBrowser without a
  // full page reload (fix/security-perf-quickwins §1.3b g).
  const [refreshKey, setRefreshKey] = useState(0);

  const handleExport = async () => {
    setExporting(true);
    setExportError(null);
    try {
      // Fetch every page because the API caps each request at 100 items.
      const exportedItems: Memory[] = [];
      let page = 1;
      let total = 0;
      do {
        const response = await memoryApi.getMemories(
          undefined,
          page,
          MEMORY_EXPORT_PAGE_SIZE,
        );
        // Early check: backend clamps page>10 → 10, declaring total from the
        // first response lets us bail out before issuing 10 doomed round-trips.
        if (response.total > MEMORY_EXPORT_MAX_ITEMS) {
          throw new Error('记忆数量超过当前导出上限，请缩小范围后重试');
        }
        if (response.page !== page) {
          throw new Error('记忆数量超过当前导出上限，请缩小范围后重试');
        }
        exportedItems.push(...response.items);
        if (
          response.items.length > MEMORY_EXPORT_PAGE_SIZE ||
          exportedItems.length > MEMORY_EXPORT_MAX_ITEMS
        ) {
          throw new Error('记忆数量超过当前导出上限，请缩小范围后重试');
        }
        total = response.total;
        page += 1;
        if (response.items.length === 0 && exportedItems.length < total) {
          throw new Error('记忆列表分页不完整，请重试');
        }
      } while (exportedItems.length < total);

      const blob = new Blob([JSON.stringify(exportedItems, null, 2)], {
        type: 'application/json',
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `sage-memories-${new Date().toISOString().slice(0, 10)}.json`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setExportError(`导出失败: ${err instanceof Error ? err.message : '未知错误'}`);
    } finally {
      setExporting(false);
    }
  };

  const handleNewMemory = () => {
    setShowNewMemory(true);
  };

  return (
    <div className="flex-1 overflow-y-auto p-5">
      <div className="flex items-center justify-between mb-5">
        <h2 className="text-[18px] font-semibold text-text">记忆库</h2>
        <div className="flex gap-2">
          <button
            onClick={handleNewMemory}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-primary text-text-inverse text-xs rounded-radius-sm hover:bg-primary-hover transition-colors"
          >
            <Plus className="w-3.5 h-3.5" />
            新建记忆
          </button>
          <button
            onClick={handleExport}
            disabled={exporting}
            className="flex items-center gap-1.5 px-3 py-1.5 border border-border text-xs rounded-radius-sm bg-surface text-text-secondary hover:text-text transition-colors disabled:opacity-50"
          >
            <Download className="w-3.5 h-3.5" />
            {exporting ? '导出中...' : '导出'}
          </button>
        </div>
      </div>

      {exportError && (
        <div className="mb-4">
          <ErrorState
            title="导出失败"
            message={exportError}
            onRetry={() => {
              setExportError(null);
              void handleExport();
            }}
            retryLabel="重新导出"
          />
        </div>
      )}

      <NewMemoryModal
        isOpen={showNewMemory}
        onClose={() => setShowNewMemory(false)}
        onSaved={() => setRefreshKey((k) => k + 1)}
      />

      <MemoryBrowser initialType="all" refreshKey={refreshKey} />
    </div>
  );
}
