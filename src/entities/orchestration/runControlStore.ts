/**
 * RunControlStore — independent Zustand store for orchestration run/task state.
 *
 * Separated from chatStreamStore so users can view run status after leaving
 * the chat page. Consumes RunEvent objects from the NDJSON stream and
 * maintains per-run snapshots with dedup (event_id / seq) and gap detection.
 */

import { create } from 'zustand';

import type {
  ConnectionStatus,
  RunEvent,
  RunSnapshot,
  TaskSummary,
} from '../../shared/api/orchEvents';

// ---------------------------------------------------------------------------
// Store state shape
// ---------------------------------------------------------------------------

export interface RunControlState {
  /** Per-run snapshots keyed by run_id */
  runs: Map<string, RunSnapshot>;

  /** Last seen seq per run (for dedup / reconnection) */
  lastSeqByRunId: Map<string, number>;

  /** Seen event_ids per run (dedup) */
  seenEventIdsByRunId: Map<string, Set<string>>;

  /** Bounded event history used by the detail timeline */
  eventsByRunId: Map<string, RunEvent[]>;

  /** Runs that need snapshot resync after a sequence gap */
  resyncRequiredRunIds: Set<string>;

  /** NDJSON connection status */
  connectionStatus: ConnectionStatus;

  /** Currently selected run_id (for detail drawer) */
  selectedRunId: string | null;

  /** Currently selected task_id (for detail drawer) */
  selectedTaskId: string | null;

  /** Error messages for UI display */
  errors: string[];

  // -- Actions --

  /** Apply a single event to the store, updating snapshots as needed */
  applyEvent: (event: RunEvent) => void;

  /** Apply a batch of events (sorted by seq ascending) */
  applyEvents: (events: RunEvent[]) => void;

  /** Set a run snapshot directly (e.g., from REST snapshot fetch) */
  setRunSnapshot: (snapshot: RunSnapshot) => void;

  /** Mark a seq gap detected → trigger resync */
  markGapDetected: (runId: string, expectedSeq: number, actualSeq: number) => void;

  /** Clear the resync marker after a fresh snapshot has been applied */
  clearResyncRequired: (runId: string) => void;

  /** Set connection status */
  setConnectionStatus: (status: ConnectionStatus) => void;

  /** Select a run/task for the detail drawer */
  selectTask: (runId: string | null, taskId: string | null) => void;

  /** Add an error message */
  addError: (message: string) => void;

  /** Clear all errors */
  clearErrors: () => void;

  /** Reset the entire store (for testing / app restart) */
  resetAll: () => void;
}

// ---------------------------------------------------------------------------
// Event reducer — translates a RunEvent into snapshot mutations
// ---------------------------------------------------------------------------

function applyEventToSnapshot(
  runs: Map<string, RunSnapshot>,
  event: RunEvent,
): Map<string, RunSnapshot> {
  const { run_id, event_type, entity, payload } = event;

  // Ensure run exists
  let run = runs.get(run_id);
  if (!run) {
    run = {
      run_id,
      status: 'draft',
      summary: {},
      last_event_seq: 0,
      updated_at: event.occurred_at,
      tasks: [],
    };
  }

  // Update last_event_seq
  run = { ...run, last_event_seq: Math.max(run.last_event_seq, event.seq), updated_at: event.occurred_at };

  // Handle run-level events
  if (event_type.startsWith('run.')) {
    const statusMap: Record<string, RunSnapshot['status']> = {
      'run.created': 'draft',
      'run.started': 'running',
      'run.completed': 'completed',
      'run.failed': 'failed',
      'run.cancelled': 'cancelled',
      'run.paused': 'paused',
    };
    if (statusMap[event_type]) {
      run = { ...run, status: statusMap[event_type] };
    }
    const next = new Map(runs);
    next.set(run_id, run);
    return next;
  }

  // Handle task-level events
  const taskId = entity.task_id;
  if (!taskId) {
    const next = new Map(runs);
    next.set(run_id, run);
    return next;
  }

  const tasks = [...run.tasks];
  let taskIdx = tasks.findIndex((t) => t.task_id === taskId);

  // Ensure task exists
  if (taskIdx < 0) {
    tasks.push({
      task_id: taskId,
      agent_id: entity.agent_id ?? null,
      status: 'pending',
      current_step_id: null,
      output_preview: null,
      error: null,
    });
    taskIdx = tasks.length - 1;
  }

  const task: TaskSummary = { ...tasks[taskIdx] };

  // Update agent_id if present
  if (entity.agent_id) {
    task.agent_id = entity.agent_id;
  }

  // Map task events to status transitions
  const taskStatusMap: Record<string, TaskSummary['status']> = {
    'task.planned': 'planned',
    'task.queued': 'queued',
    'task.started': 'running',
    'task.waiting_input': 'waiting_input',
    'task.waiting_approval': 'waiting_approval',
    'task.retrying': 'retrying',
    'task.succeeded': 'succeeded',
    'task.completed': 'completed',
    'task.failed': 'failed',
    'task.cancel_requested': 'cancelled',
    'task.cancelled': 'cancelled',
    'task.blocked': 'blocked',
  };

  if (taskStatusMap[event_type]) {
    task.status = taskStatusMap[event_type];
  }

  // Update current_step_id from step events
  if (event_type.startsWith('task.step.') && entity.step_id) {
    task.current_step_id = entity.step_id;
  }

  // Update output_preview / error from payload
  if (payload.output_preview && typeof payload.output_preview === 'string') {
    task.output_preview = payload.output_preview as string;
  }
  if (payload.error && typeof payload.error === 'string') {
    task.error = payload.error as string;
  }

  tasks[taskIdx] = task;

  // Update run summary counts
  const summary: Record<string, number> = {};
  for (const t of tasks) {
    summary[t.status] = (summary[t.status] ?? 0) + 1;
  }

  run = { ...run, tasks, summary };

  // Derive run-level status from terminal task states.
  // Priority: failed > cancelled > completed. Run-level events
  // (run.completed/run.failed/run.cancelled) always take precedence
  // over this heuristic — they're applied in the run.* branch above.
  const allTerminal = tasks.every(
    (t) =>
      t.status === 'succeeded' ||
      t.status === 'completed' ||
      t.status === 'failed' ||
      t.status === 'cancelled',
  );
  if (allTerminal && tasks.length > 0 && run.status === 'running') {
    const hasFailed = tasks.some((t) => t.status === 'failed');
    const hasCancelled = tasks.some((t) => t.status === 'cancelled');
    const derivedStatus: RunSnapshot['status'] = hasFailed
      ? 'failed'
      : hasCancelled
        ? 'cancelled'
        : 'completed';
    run = { ...run, status: derivedStatus };
  }

  const next = new Map(runs);
  next.set(run_id, run);
  return next;
}

// ---------------------------------------------------------------------------
// Store creation
// ---------------------------------------------------------------------------

export const useRunControlStore = create<RunControlState>((set, get) => ({
  runs: new Map<string, RunSnapshot>(),
  lastSeqByRunId: new Map<string, number>(),
  seenEventIdsByRunId: new Map<string, Set<string>>(),
  eventsByRunId: new Map<string, RunEvent[]>(),
  resyncRequiredRunIds: new Set<string>(),
  connectionStatus: 'disconnected' as ConnectionStatus,
  selectedRunId: null as string | null,
  selectedTaskId: null as string | null,
  errors: [] as string[],

  applyEvent: (event: RunEvent) => {
    set((prev) => {
      const { run_id, seq, event_id } = event;

      // Dedup by event_id and reject sequence regressions.
      const seen = prev.seenEventIdsByRunId.get(run_id) ?? new Set<string>();
      const lastSeq = prev.lastSeqByRunId.get(run_id) ?? 0;
      if (seen.has(event_id) || (lastSeq > 0 && seq <= lastSeq)) {
        return prev;
      }

      // Apply event to snapshots
      const newRuns = applyEventToSnapshot(prev.runs, event);

      // Keep a bounded immutable event history for the timeline.
      const newEvents = new Map(prev.eventsByRunId);
      const history = [...(newEvents.get(run_id) ?? []), event];
      newEvents.set(run_id, history.slice(-1000));

      // Update seen + lastSeq
      const newSeen = new Map(prev.seenEventIdsByRunId);
      newSeen.set(run_id, new Set([...seen, event_id]));

      const newLastSeq = new Map(prev.lastSeqByRunId);
      newLastSeq.set(run_id, seq);

      return {
        runs: newRuns,
        eventsByRunId: newEvents,
        seenEventIdsByRunId: newSeen,
        lastSeqByRunId: newLastSeq,
      };
    });
  },

  applyEvents: (events: RunEvent[]) => {
    // Sort by seq ascending to ensure correct ordering
    const sorted = [...events].sort((a, b) => a.seq - b.seq);
    for (const event of sorted) {
      get().applyEvent(event);
    }
  },

  setRunSnapshot: (snapshot: RunSnapshot) => {
    set((prev) => {
      const newRuns = new Map(prev.runs);
      newRuns.set(snapshot.run_id, snapshot);
      const newLastSeq = new Map(prev.lastSeqByRunId);
      newLastSeq.set(snapshot.run_id, snapshot.last_event_seq);
      const newResync = new Set(prev.resyncRequiredRunIds);
      newResync.delete(snapshot.run_id);
      return {
        runs: newRuns,
        lastSeqByRunId: newLastSeq,
        resyncRequiredRunIds: newResync,
      };
    });
  },

  markGapDetected: (runId: string, expectedSeq: number, actualSeq: number) => {
    set((prev) => {
      const next = new Set(prev.resyncRequiredRunIds);
      next.add(runId);
      return { resyncRequiredRunIds: next };
    });
    get().addError(`Seq gap detected for run ${runId}: expected ${expectedSeq}, got ${actualSeq}`);
  },

  clearResyncRequired: (runId: string) => {
    set((prev) => {
      const next = new Set(prev.resyncRequiredRunIds);
      next.delete(runId);
      return { resyncRequiredRunIds: next };
    });
  },

  setConnectionStatus: (status: ConnectionStatus) => {
    set({ connectionStatus: status });
  },

  selectTask: (runId: string | null, taskId: string | null) => {
    set({ selectedRunId: runId, selectedTaskId: taskId });
  },

  addError: (message: string) => {
    set((prev) => ({ errors: [...prev.errors, message] }));
  },

  clearErrors: () => {
    set({ errors: [] });
  },

  resetAll: () => {
    set({
      runs: new Map<string, RunSnapshot>(),
      lastSeqByRunId: new Map<string, number>(),
      seenEventIdsByRunId: new Map<string, Set<string>>(),
      eventsByRunId: new Map<string, RunEvent[]>(),
      resyncRequiredRunIds: new Set<string>(),
      connectionStatus: 'disconnected',
      selectedRunId: null,
      selectedTaskId: null,
      errors: [],
    });
  },
}));
