/**
 * LaneBoard - three-column board view of orchestration lanes.
 *
 * Displays lanes grouped by status (active / blocked / finished) with
 * real-time updates via the laneBoardStore. Each lane card shows the
 * lane ID, bound agent, status badge, and heartbeat freshness.
 */
import { useEffect, useMemo, useState } from 'react';

import { useLaneBoardStore } from '../../entities/orchestration/laneBoardStore';
import type { Lane, LaneBoardGroup, LaneStatus } from '../../shared/api/types';

const STATUS_LABELS: Record<LaneStatus, string> = {
  created: '已创建',
  ready: '就绪',
  running: '运行中',
  blocked: '阻塞',
  succeeded: '成功',
  failed: '失败',
  stopped: '已停止',
  cancelled: '已取消',
};

const STATUS_COLORS: Record<LaneStatus, string> = {
  created: 'bg-bg-subtle text-text-secondary',
  ready: 'bg-blue-100 text-blue-800',
  running: 'bg-green-100 text-green-800',
  blocked: 'bg-yellow-100 text-yellow-800',
  succeeded: 'bg-emerald-100 text-emerald-800',
  failed: 'bg-red-100 text-red-800',
  stopped: 'bg-gray-200 text-gray-700',
  cancelled: 'bg-gray-200 text-gray-700',
};

interface LaneCardProps {
  lane: Lane;
  onCancel: (laneId: string) => void;
}

function LaneCard({ lane, onCancel }: LaneCardProps) {
  const statusLabel = STATUS_LABELS[lane.status] ?? lane.status;
  const statusColor = STATUS_COLORS[lane.status] ?? 'bg-bg-subtle text-text-secondary';

  const heartbeatLabel = useMemo(() => {
    if (!lane.heartbeat) return '—';
    const age = Date.now() - lane.heartbeat.last_ping_at;
    if (!lane.heartbeat.transport_alive) return 'transport dead';
    if (age < 60_000) return `${Math.floor(age / 1000)}s ago`;
    if (age < 3_600_000) return `${Math.floor(age / 60_000)}m ago`;
    return `${Math.floor(age / 3_600_000)}h ago`;
  }, [lane.heartbeat]);

  const isTerminal = ['succeeded', 'failed', 'stopped', 'cancelled'].includes(lane.status);

  return (
    <div className="p-3 rounded-lg border border-border bg-bg-surface hover:border-border-hover transition-colors">
      <div className="flex items-center justify-between mb-1">
        <span className="font-mono text-xs text-text-tertiary truncate">{lane.lane_id}</span>
        <span className={`px-2 py-0.5 text-xs rounded-full whitespace-nowrap ${statusColor}`}>
          {statusLabel}
        </span>
      </div>
      <div className="text-sm text-text-secondary mb-1 truncate">task: {lane.task_id}</div>
      <div className="flex items-center justify-between text-xs text-text-tertiary">
        <span>agent: {lane.agent_id ?? '—'}</span>
        <span title={lane.heartbeat?.status ?? 'no heartbeat'}>{heartbeatLabel}</span>
      </div>
      {lane.error && (
        <div className="mt-1 text-xs text-red-600 truncate" title={lane.error}>
          {lane.error}
        </div>
      )}
      {!isTerminal && (
        <button
          onClick={() => onCancel(lane.lane_id)}
          className="mt-2 text-xs text-red-600 hover:text-red-800"
        >
          取消
        </button>
      )}
    </div>
  );
}

interface ColumnProps {
  title: string;
  lanes: Lane[];
  onCancel: (laneId: string) => void;
}

function Column({ title, lanes, onCancel }: ColumnProps) {
  return (
    <div className="flex-1 min-w-0">
      <div className="flex items-center justify-between mb-2">
        <h3 className="font-medium text-sm">{title}</h3>
        <span className="text-xs text-text-tertiary">{lanes.length}</span>
      </div>
      <div className="space-y-2">
        {lanes.length === 0 ? (
          <div className="text-xs text-text-tertiary text-center py-4">(无)</div>
        ) : (
          lanes.map((lane) => <LaneCard key={lane.lane_id} lane={lane} onCancel={onCancel} />)
        )}
      </div>
    </div>
  );
}

export function LaneBoard() {
  const lanes = useLaneBoardStore((s) => s.lanes);
  const loading = useLaneBoardStore((s) => s.loading);
  const error = useLaneBoardStore((s) => s.error);
  const load = useLaneBoardStore((s) => s.load);
  const cancel = useLaneBoardStore((s) => s.cancel);
  const [teamId] = useState<string | undefined>(undefined);

  useEffect(() => {
    void load(teamId);
  }, [load, teamId]);

  const board: LaneBoardGroup = useMemo(() => {
    const active: Lane[] = [];
    const blocked: Lane[] = [];
    const finished: Lane[] = [];
    for (const lane of lanes) {
      if (['created', 'ready', 'running'].includes(lane.status)) {
        active.push(lane);
      } else if (lane.status === 'blocked') {
        blocked.push(lane);
      } else {
        finished.push(lane);
      }
    }
    return { active, blocked, finished };
  }, [lanes]);

  const handleCancel = (laneId: string) => {
    void cancel(laneId).catch(() => {
      // Error already stored in state
    });
  };

  if (loading && lanes.length === 0) {
    return <div className="p-4 text-center text-text-secondary">加载中…</div>;
  }

  if (error) {
    return <div className="p-4 text-center text-red-600">错误: {error}</div>;
  }

  return (
    <div className="flex gap-4 p-4">
      <Column title="活跃 (Active)" lanes={board.active} onCancel={handleCancel} />
      <Column title="阻塞 (Blocked)" lanes={board.blocked} onCancel={handleCancel} />
      <Column title="已完成 (Finished)" lanes={board.finished} onCancel={handleCancel} />
    </div>
  );
}
