/**
 * Canonical orchestration event types — mirrors backend/domain/orch_events.py
 *
 * Phase 2 of the subagent realtime monitoring plan. These types define the
 * frontend representation of the unified RunEvent envelope, RunSnapshot, and
 * TaskSummary that the backend publishes via NDJSON.
 *
 * The backend assigns `seq` (per-run monotonic), `event_id`, and `occurred_at`.
 * The frontend consumes these events in order, deduplicates by `event_id`, and
 * detects gaps via `seq`.
 */

// ---------------------------------------------------------------------------
// Event type enumerations — kept in sync with Python TaskEventType / etc.
// ---------------------------------------------------------------------------

export type TaskEventType =
  | 'task.planned'
  | 'task.queued'
  | 'task.started'
  | 'task.waiting_input'
  | 'task.waiting_approval'
  | 'task.retrying'
  | 'task.succeeded'
  | 'task.failed'
  | 'task.cancel_requested'
  | 'task.cancelled'
  | 'task.blocked'
  | 'task.progress';

export type StepEventType =
  | 'task.step.started'
  | 'task.step.completed'
  | 'task.step.failed'
  | 'task.step.progress';

export type ControlEventType =
  | 'task.context.append_requested'
  | 'task.context.appended'
  | 'task.context.delivered'
  | 'task.context.acknowledged'
  | 'task.run_requested'
  | 'task.approval_requested'
  | 'task.approval_resolved';

export type RunEventType =
  | TaskEventType
  | StepEventType
  | ControlEventType
  | 'run.created'
  | 'run.started'
  | 'run.completed'
  | 'run.failed'
  | 'run.cancelled'
  | 'run.paused';

// ---------------------------------------------------------------------------
// RunEvent — the unified envelope
// ---------------------------------------------------------------------------

export interface RunEvent {
  /** Unique event identifier (backend-generated UUID) */
  event_id: string;
  /** Run this event belongs to */
  run_id: string;
  /** Per-run monotonic sequence number (backend-assigned) */
  seq: number;
  /** Event type (see TaskEventType / StepEventType / ControlEventType) */
  event_type: RunEventType;
  /** Unix timestamp in milliseconds when the event occurred */
  occurred_at: number;
  /** Producer identifier (e.g., "lane-executor", "chat-dispatcher") */
  producer: string;
  /** Producer generation — newer generations supersede older ones */
  producer_generation: number;
  /** Entity identifiers (task_id, lane_id, step_id, agent_id — whichever apply) */
  entity: RunEventEntity;
  /** Event payload — structure depends on event_type */
  payload: Record<string, unknown>;
  /** Visibility: "user" (shown to user) or "internal" (debug only) */
  visibility: 'user' | 'internal';
  /** Schema version for forward compatibility */
  schema_version: string;
  /** Optional idempotency key for commands */
  command_id?: string;
}

export interface RunEventEntity {
  task_id?: string;
  lane_id?: string;
  step_id?: string;
  agent_id?: string;
}

// ---------------------------------------------------------------------------
// RunSnapshot — aggregated view of a run's current state
// ---------------------------------------------------------------------------

export interface RunSnapshot {
  run_id: string;
  status: 'draft' | 'running' | 'completed' | 'failed' | 'cancelled' | 'paused';
  summary: Record<string, number>;
  last_event_seq: number;
  updated_at: number;
  tasks: TaskSummary[];
}

export interface TaskSummary {
  task_id: string;
  agent_id: string | null;
  status:
    | 'pending'
    | 'planned'
    | 'queued'
    | 'running'
    | 'retrying'
    | 'succeeded'
    | 'completed'
    | 'failed'
    | 'cancelled'
    | 'waiting_input'
    | 'waiting_approval'
    | 'blocked';
  current_step_id: string | null;
  output_preview: string | null;
  error: string | null;
  /** Monotonic counter bumped on every task event (CAS baseline for steer). */
  revision?: number;
}

// ---------------------------------------------------------------------------
// Connection status for the NDJSON subscription
// ---------------------------------------------------------------------------

export type ConnectionStatus = 'connecting' | 'connected' | 'disconnected' | 'resyncing';

// ---------------------------------------------------------------------------
// Type guards
// ---------------------------------------------------------------------------

export function isTaskEvent(event: RunEvent): boolean {
  return event.event_type.startsWith('task.') && !event.event_type.startsWith('task.step.');
}

export function isStepEvent(event: RunEvent): boolean {
  return event.event_type.startsWith('task.step.');
}

export function isControlEvent(event: RunEvent): boolean {
  return (
    event.event_type.startsWith('task.context.') ||
    event.event_type.startsWith('task.run_') ||
    event.event_type.startsWith('task.approval_')
  );
}

export function isRunEvent(event: RunEvent): boolean {
  return event.event_type.startsWith('run.');
}

export function isTerminalTaskStatus(status: TaskSummary['status']): boolean {
  return (
    status === 'succeeded' ||
    status === 'completed' ||
    status === 'failed' ||
    status === 'cancelled'
  );
}
