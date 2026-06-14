import { Plus, Download } from 'lucide-react';
import { useState } from 'react';

import { memoryApi } from '../shared/api/api';
import { ErrorState } from '../shared/ui/ErrorState';
import { MemoryBrowser, NewMemoryModal } from '../widgets/memory';

export function Memory() {
  const [showNewMemory, setShowNewMemory] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);

  const handleExport = async () => {
    setExporting(true);
    setExportError(null);
    try {
      const memories = await memoryApi.getMemories(undefined, 1, 1000);
      const blob = new Blob([JSON.stringify(memories, null, 2)], { type: 'application/json' });
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

      {showNewMemory && <NewMemoryModal onClose={() => setShowNewMemory(false)} />}

      <MemoryBrowser initialType="all" />
    </div>
  );
}
