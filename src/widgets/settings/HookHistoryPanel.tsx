import { useCallback, useEffect, useState } from 'react';

import { backendRequest } from '../../shared/api/backendRequest';

interface HookHistoryRecord {
  id: string;
  occurred_at: string;
  hook_id: string;
  hook_type: string;
  event: string;
  tool_name: string;
  decision: string;
  duration_ms: number;
  reason?: string | null;
}

interface HookHistoryPanelProps {
  refreshToken?: number;
}

const DECISION_LABELS: Record<string, string> = {
  allow: '允许',
  deny: '拒绝',
  modify: '修改',
  noop: '忽略',
};

export function HookHistoryPanel({ refreshToken = 0 }: HookHistoryPanelProps): JSX.Element {
  const [records, setRecords] = useState<HookHistoryRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [clearing, setClearing] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const response = await backendRequest<{ records: HookHistoryRecord[] }>({
        method: 'GET',
        path: '/api/v1/hooks/history?limit=50',
      });
      setRecords(Array.isArray(response?.records) ? response.records : []);
    } catch {
      setRecords([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load, refreshToken]);

  const clear = async (): Promise<void> => {
    setClearing(true);
    try {
      await backendRequest({ method: 'DELETE', path: '/api/v1/hooks/history' });
      setRecords([]);
    } finally {
      setClearing(false);
    }
  };

  return (
    <div className="mt-4 border-t border-border pt-3" data-testid="hook-history-panel">
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs text-text-secondary">Hook 执行历史</span>
        <button
          type="button"
          className="text-[10px] text-text-secondary hover:text-red-500 disabled:opacity-50"
          onClick={() => void clear()}
          disabled={clearing || records.length === 0}
        >
          {clearing ? '清空中…' : '清空'}
        </button>
      </div>
      {loading ? (
        <div className="text-[10px] text-muted">加载中…</div>
      ) : records.length === 0 ? (
        <div className="text-[10px] text-muted">暂无执行记录</div>
      ) : (
        <div className="space-y-1.5 max-h-52 overflow-y-auto">
          {records.map((record) => (
            <div
              key={record.id}
              className="flex items-start gap-2 text-[10px] border-b border-border/50 pb-1.5"
            >
              <span
                className={
                  record.decision === 'deny'
                    ? 'text-red-500'
                    : record.decision === 'noop'
                      ? 'text-amber-500'
                      : 'text-green-600'
                }
              >
                {DECISION_LABELS[record.decision] ?? record.decision}
              </span>
              <span className="flex-1 min-w-0 truncate" title={record.reason ?? undefined}>
                {record.hook_id} → {record.tool_name || '*'}
                {record.reason ? `: ${record.reason}` : ''}
              </span>
              <span className="text-muted flex-shrink-0">{Math.round(record.duration_ms)}ms</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
