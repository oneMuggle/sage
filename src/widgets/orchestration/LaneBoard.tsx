/**
 * LaneBoard - three-column board view of orchestration lanes.
 *
 * Displays lanes grouped by status (active / blocked / finished) with
 * real-time updates via the laneBoardStore. Each lane card shows the
 * lane ID, bound agent, status badge, and heartbeat freshness.
 */
import { useEffect, useMemo, useState } from 'react';

import { useLaneBoardStore } from '../../entities/orchestration/laneBoardStore';
import type {
  FreshnessSummaryInfo,
  Lane,
  LaneBoardGroup,
  LaneStatus,
} from '../../shared/api/types';
import { useI18n, type TranslationKey } from '../../shared/lib/i18n';

const STATUS_COLORS: Record<LaneStatus, string> = {
  created: 'bg-bg-subtle text-text-secondary',
  ready: 'bg-blue-100 text-blue-800',
  running: 'bg-green-100 text-green-800',
  blocked: 'bg-yellow-100 text-yellow-800',
  succeeded: 'bg-emerald-100 text-emerald-800',
  failed: 'bg-red-100 text-red-800',
  stopped: 'bg-line text-muted',
  cancelled: 'bg-line text-muted',
};

interface LaneCardProps {
  lane: Lane;
  onCancel: (laneId: string) => void;
}

function LaneCard({ lane, onCancel }: LaneCardProps) {
  const { t } = useI18n();
  // Status labels are built inside the component so the translated
  // strings track the active locale (module-level maps can't call t()).
  const statusLabels: Record<LaneStatus, string> = {
    created: t('orchestration.status.created'),
    ready: t('orchestration.status.ready'),
    running: t('orchestration.status.running'),
    blocked: t('orchestration.status.blocked'),
    succeeded: t('orchestration.status.succeeded'),
    failed: t('orchestration.status.failed'),
    stopped: t('orchestration.status.stopped'),
    cancelled: t('orchestration.status.cancelled'),
  };
  const statusLabel = statusLabels[lane.status] ?? lane.status;
  const statusColor = STATUS_COLORS[lane.status] ?? 'bg-bg-subtle text-text-secondary';
  // M5: planner / sub-agent lanes carry a metadata.source marker.
  const source = typeof lane.metadata?.source === 'string' ? lane.metadata.source : null;

  const heartbeatLabel = useMemo(() => {
    if (!lane.heartbeat) return t('orchestration.heartbeat.none');
    const age = Date.now() - lane.heartbeat.last_ping_at;
    if (!lane.heartbeat.transport_alive) return t('orchestration.heartbeat.transportDead');
    if (age < 60_000) return `${Math.floor(age / 1000)}${t('orchestration.heartbeat.secondsAgo')}`;
    if (age < 3_600_000)
      return `${Math.floor(age / 60_000)}${t('orchestration.heartbeat.minutesAgo')}`;
    return `${Math.floor(age / 3_600_000)}${t('orchestration.heartbeat.hoursAgo')}`;
  }, [lane.heartbeat, t]);

  const isTerminal = ['succeeded', 'failed', 'stopped', 'cancelled'].includes(lane.status);

  return (
    <div className="p-3 rounded-lg border border-border bg-bg-surface hover:border-border-hover transition-colors">
      <div className="flex items-center justify-between gap-1 mb-1">
        <span className="font-mono text-xs text-text-tertiary truncate">{lane.lane_id}</span>
        <span className="flex items-center gap-1 shrink-0">
          {source === 'subagent' && (
            <span
              data-testid="lane-source-badge"
              className="px-2 py-0.5 text-xs rounded-full whitespace-nowrap bg-purple-100 text-purple-800"
            >
              {t('orchestration.badge.subagent')}
            </span>
          )}
          {source === 'planner' && (
            <span
              data-testid="lane-source-badge"
              className="px-2 py-0.5 text-xs rounded-full whitespace-nowrap bg-indigo-100 text-indigo-800"
            >
              {t('orchestration.badge.planner')}
            </span>
          )}
          <span className={`px-2 py-0.5 text-xs rounded-full whitespace-nowrap ${statusColor}`}>
            {statusLabel}
          </span>
        </span>
      </div>
      <div className="text-sm text-text-secondary mb-1 truncate">
        {t('orchestration.lane.task')} {lane.task_id}
      </div>
      <div className="flex items-center justify-between text-xs text-text-tertiary">
        <span>
          {t('orchestration.lane.agent')} {lane.agent_id ?? t('orchestration.heartbeat.none')}
        </span>
        <span title={lane.heartbeat?.status ?? t('orchestration.heartbeat.noHeartbeat')}>
          {heartbeatLabel}
        </span>
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
          {t('common.cancel')}
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

/** P2-5: overall_level → 色徽章映射（fresh=green / stale=yellow / dead=red）。 */
const FRESHNESS_LEVEL_COLORS: Record<FreshnessSummaryInfo['overall_level'], string> = {
  fresh: 'bg-green-100 text-green-800',
  stale: 'bg-yellow-100 text-yellow-800',
  dead: 'bg-red-100 text-red-800',
};

const FRESHNESS_LEVEL_I18N: Record<
  FreshnessSummaryInfo['overall_level'],
  TranslationKey
> = {
  fresh: 'orchestration.board.level.fresh',
  stale: 'orchestration.board.level.stale',
  dead: 'orchestration.board.level.dead',
};

function FreshnessBadge({ summary }: { summary: FreshnessSummaryInfo }) {
  const { t } = useI18n();
  // 项目 t() 不支持占位符插值 —— 沿用 Orchestration.tsx 的调用点
  // .replace() 先例（与 toast.create_success 的 {count} 同模式）。
  const summaryText = t('orchestration.board.summary')
    .replace('{total}', String(summary.total))
    .replace('{fresh}', String(summary.fresh))
    .replace('{stale}', String(summary.stale))
    .replace('{dead}', String(summary.dead));
  const levelLabel = t(FRESHNESS_LEVEL_I18N[summary.overall_level]);
  return (
    <div
      data-testid="board-freshness-summary"
      className="flex items-center gap-2 mb-3 text-xs text-text-secondary"
    >
      <span>{summaryText}</span>
      <span
        data-testid="board-freshness-badge"
        className={`px-2 py-0.5 rounded-full whitespace-nowrap ${FRESHNESS_LEVEL_COLORS[summary.overall_level]}`}
      >
        {levelLabel}
      </span>
    </div>
  );
}
function Column({ title, lanes, onCancel }: ColumnProps) {
  const { t } = useI18n();
  return (
    <div className="flex-1 min-w-0">
      <div className="flex items-center justify-between mb-2">
        <h3 className="font-medium text-sm">{title}</h3>
        <span className="text-xs text-text-tertiary">{lanes.length}</span>
      </div>
      <div className="space-y-2">
        {lanes.length === 0 ? (
          <div className="text-xs text-text-tertiary text-center py-4">
            {t('orchestration.column.empty')}
          </div>
        ) : (
          lanes.map((lane) => <LaneCard key={lane.lane_id} lane={lane} onCancel={onCancel} />)
        )}
      </div>
    </div>
  );
}

export function LaneBoard() {
  const { t } = useI18n();
  const lanes = useLaneBoardStore((s) => s.lanes);
  const boardSummary = useLaneBoardStore((s) => s.boardSummary);
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
    return <div className="p-4 text-center text-text-secondary">{t('orchestration.loading')}</div>;
  }

  if (error) {
    return (
      <div className="p-4 text-center text-red-600">
        {t('orchestration.error')} {error}
      </div>
    );
  }

  return (
    <div className="p-4">
      {boardSummary && <FreshnessBadge summary={boardSummary} />}
      <div className="flex gap-4">
        <Column
          title={t('orchestration.column.active')}
          lanes={board.active}
          onCancel={handleCancel}
        />
        <Column
          title={t('orchestration.column.blocked')}
          lanes={board.blocked}
          onCancel={handleCancel}
        />
        <Column
          title={t('orchestration.column.finished')}
          lanes={board.finished}
          onCancel={handleCancel}
        />
      </div>
    </div>
  );
}
