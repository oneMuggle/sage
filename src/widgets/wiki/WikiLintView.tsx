// WikiLintView - Wiki 质量检查结果视图
import { AlertTriangle, CheckCircle2, Loader2, RefreshCw } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';

import { useLintStore } from '../../entities/wiki/lint-store';

import { LintItemCard } from './LintItemCard';

interface WikiLintViewProps {
  projectPath: string;
}

type SeverityFilter = 'all' | 'error' | 'warning' | 'info';

const SEVERITY_FILTERS: { value: SeverityFilter; label: string }[] = [
  { value: 'all', label: '全部' },
  { value: 'error', label: '错误' },
  { value: 'warning', label: '警告' },
  { value: 'info', label: '提示' },
];

function formatLastRun(ts: number | null): string {
  if (!ts) return '从未运行';
  const d = new Date(ts);
  return d.toLocaleString();
}

export function WikiLintView({ projectPath }: WikiLintViewProps) {
  const items = useLintStore((s) => s.items);
  const isLoading = useLintStore((s) => s.isLoading);
  const lastRunAt = useLintStore((s) => s.lastRunAt);
  const error = useLintStore((s) => s.error);
  const runLint = useLintStore((s) => s.runLint);

  const [severity, setSeverity] = useState<SeverityFilter>('all');

  // 首次挂载 + projectPath 变化时自动跑一次
  useEffect(() => {
    if (projectPath) {
      void runLint(projectPath);
    }
  }, [projectPath, runLint]);

  const filtered = useMemo(() => {
    if (severity === 'all') return items;
    return items.filter((i) => i.severity === severity);
  }, [items, severity]);

  const counts = useMemo(
    () => ({
      error: items.filter((i) => i.severity === 'error').length,
      warning: items.filter((i) => i.severity === 'warning').length,
      info: items.filter((i) => i.severity === 'info').length,
    }),
    [items],
  );

  const handleRun = () => {
    void runLint(projectPath);
  };

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* Toolbar */}
      <div className="flex items-center gap-2 border-b border-border px-4 py-3">
        <button
          onClick={handleRun}
          disabled={isLoading}
          className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-sm text-text-inverse hover:bg-primary/90 disabled:opacity-50 transition-colors"
        >
          {isLoading ? (
            <>
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              运行中...
            </>
          ) : (
            <>
              <RefreshCw className="h-3.5 w-3.5" />
              运行检查
            </>
          )}
        </button>

        <div className="ml-auto flex items-center gap-3 text-xs text-muted">
          <span>
            共 {items.length} 项:
            <span className="ml-1 text-red-500">{counts.error}</span> /
            <span className="ml-1 text-amber-500">{counts.warning}</span> /
            <span className="ml-1 text-blue-500">{counts.info}</span>
          </span>
          <span className="text-muted/70">上次: {formatLastRun(lastRunAt)}</span>
        </div>
      </div>

      {/* Severity filter */}
      <div className="flex items-center gap-1 border-b border-border px-4 py-2">
        {SEVERITY_FILTERS.map((f) => (
          <button
            key={f.value}
            onClick={() => setSeverity(f.value)}
            data-active={severity === f.value}
            className={`rounded-md px-3 py-1 text-xs transition-colors ${
              severity === f.value
                ? 'bg-primary text-text-inverse'
                : 'text-muted hover:bg-bg-muted hover:text-text'
            }`}
          >
            {f.label}
          </button>
        ))}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-auto px-4 py-4">
        {error && (
          <div className="mb-3 flex items-start gap-2 rounded-md border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-700">
            <AlertTriangle className="mt-0.5 h-4 w-4 flex-shrink-0" />
            <div className="flex-1">
              <p className="font-medium">质量检查失败</p>
              <p className="text-xs">{error}</p>
            </div>
          </div>
        )}

        {isLoading && items.length === 0 && (
          <div className="flex h-full items-center justify-center text-muted text-sm">
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            正在扫描 Wiki...
          </div>
        )}

        {!isLoading && filtered.length === 0 && (
          <div className="flex h-full flex-col items-center justify-center text-muted">
            <CheckCircle2 className="mb-2 h-8 w-8 text-green-500" />
            <p className="text-sm">
              {items.length === 0 ? '尚未运行质量检查,或项目完全合规' : '当前筛选下无问题'}
            </p>
          </div>
        )}

        <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
          {filtered.map((item) => (
            <LintItemCard key={item.id} item={item} />
          ))}
        </div>
      </div>
    </div>
  );
}
