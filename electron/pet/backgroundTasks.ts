/**
 * Main-process background sources for the pet (beyond Task Center reports).
 *
 * Task Center only knows tasks the renderer registered. Two long-running
 * sources never show up there:
 *   - orchestration lanes (a planner run fans out into many lanes; the
 *     Orchestration page only streams events while it is open);
 *   - scheduled tasks (the backend records last_attempt/last_status).
 *
 * This module maps their REST payloads into the same PetTaskReport shape used
 * by Task Center, defensively (untrusted-ish JSON, bounded counts). Lanes are
 * grouped per orchestration team so one run appears as one panel row instead
 * of five lanes.
 */
import type { PetTaskReport, PetTaskStatus } from './types';

const FAILED_WINDOW_MS = 10 * 60_000;
const MAX_TASKS = 20;

const STATUS_PRIORITY: Record<PetTaskStatus, number> = {
  awaiting_approval: 100,
  failed: 90,
  running: 60,
  queued: 50,
  paused: 40,
  succeeded: 0,
  cancelled: 0,
};

const LANE_STATUS: Record<string, PetTaskStatus> = {
  created: 'queued',
  ready: 'queued',
  queued: 'queued',
  running: 'running',
  blocked: 'awaiting_approval',
  failed: 'failed',
  succeeded: 'succeeded',
  stopped: 'cancelled',
  cancelled: 'cancelled',
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function text(value: unknown, max: number): string | null {
  if (typeof value !== 'string') return null;
  const trimmed = value.trim();
  return trimmed ? trimmed.slice(0, max) : null;
}

function ms(value: unknown): number | null {
  if (typeof value !== 'number' || !Number.isFinite(value) || value <= 0) return null;
  return Math.floor(value);
}

interface LaneInfo {
  laneId: string;
  team: string;
  status: PetTaskStatus;
  taskName: string | null;
  goal: string | null;
  startedAt: number | null;
  completedAt: number | null;
  error: string | null;
}

function parseLane(raw: unknown): LaneInfo | null {
  if (!isRecord(raw)) return null;
  const laneId = text(raw.lane_id, 128);
  const rawStatus = typeof raw.status === 'string' ? raw.status : '';
  const status = LANE_STATUS[rawStatus];
  if (!laneId || !status) return null;
  const metadata = isRecord(raw.metadata) ? raw.metadata : {};
  const team = text(metadata.team_id, 128) ?? laneId;
  return {
    laneId,
    team,
    status,
    taskName: text(metadata.task_name, 120),
    goal: text(metadata.goal, 200),
    startedAt: ms(raw.started_at) ?? ms(raw.created_at),
    completedAt: ms(raw.completed_at),
    error: text(raw.error, 240),
  };
}

function isTerminalStatus(status: PetTaskStatus): boolean {
  return status === 'succeeded' || status === 'cancelled';
}

/**
 * Group lanes by orchestration team and keep only groups that still have an
 * active lane (or a recent failure). Succeeded/cancelled-only groups would
 * otherwise accumulate in the panel forever.
 */
export function mapOrchestrationLanes(raw: unknown, now = Date.now()): PetTaskReport[] {
  if (!Array.isArray(raw)) return [];
  const groups = new Map<string, LaneInfo[]>();
  for (const item of raw) {
    const lane = parseLane(item);
    if (!lane) continue;
    const list = groups.get(lane.team);
    if (list) list.push(lane);
    else groups.set(lane.team, [lane]);
  }

  const reports: PetTaskReport[] = [];
  for (const [team, lanes] of groups) {
    const visible = lanes.filter((lane) => {
      if (isTerminalStatus(lane.status)) return false;
      if (lane.status !== 'failed') return true;
      return lane.completedAt !== null && lane.completedAt >= now - FAILED_WINDOW_MS;
    });
    if (visible.length === 0) continue;
    const best = [...visible].sort(
      (a, b) => STATUS_PRIORITY[b.status] - STATUS_PRIORITY[a.status],
    )[0]!;
    const goal = visible.find((lane) => lane.goal)?.goal ?? null;
    const names = Array.from(
      new Set(visible.map((lane) => lane.taskName).filter((name): name is string => Boolean(name))),
    );
    const title =
      goal ?? (names.length > 1 ? `${names[0]} 等 ${names.length} 个任务` : (names[0] ?? team));
    const started = visible.reduce<number | null>((min, lane) => {
      if (lane.startedAt === null) return min;
      return min === null ? lane.startedAt : Math.min(min, lane.startedAt);
    }, null);
    reports.push({
      id: `orch:${team}`,
      kind: 'orchestration',
      title,
      status: best.status,
      phase: names.length > 1 ? `${names.length} 个任务` : null,
      percent: null,
      sessionId: null,
      runId: team,
      error: best.error ?? visible.find((lane) => lane.error)?.error ?? null,
      startedAt: started,
      finishedAt: best.status === 'failed' ? best.completedAt : null,
    });
  }

  return reports
    .sort((a, b) => (b.startedAt ?? 0) - (a.startedAt ?? 0))
    .slice(0, MAX_TASKS);
}

/**
 * Scheduled tasks are delivery jobs: the backend has no persistent "running"
 * state, so only recent delivery failures are worth interrupting the pet for.
 */
export function mapScheduledTasks(raw: unknown, now = Date.now()): PetTaskReport[] {
  if (!Array.isArray(raw)) return [];
  const reports: PetTaskReport[] = [];
  for (const item of raw) {
    if (!isRecord(item)) continue;
    const id = text(item.id, 128);
    const name = text(item.name, 200);
    if (!id || !name) continue;
    if (item.last_status !== 'failed') continue;
    const at = ms(item.last_attempt);
    if (at === null || at < now - FAILED_WINDOW_MS) continue;
    reports.push({
      id: `sched:${id}`,
      kind: 'scheduled',
      title: name,
      status: 'failed',
      phase: null,
      percent: null,
      sessionId: text(item.session_id, 128),
      runId: null,
      error: text(item.last_error, 240),
      startedAt: at,
      finishedAt: at,
    });
  }
  return reports.sort((a, b) => (b.finishedAt ?? 0) - (a.finishedAt ?? 0)).slice(0, MAX_TASKS);
}
