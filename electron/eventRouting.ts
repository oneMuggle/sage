export interface OrchEventSubscription {
  runId: string;
  afterSeq: number;
}

/**
 * Parse dynamic orchestration event channel names.
 *
 * Format: `orch-events-{runId}` or `orch-events-{runId}-seq-{afterSeq}`.
 * runId may contain hyphens — the backend generates `orch-<uuid4>` and
 * `api-team-<hex12>` — so the runId group must not exclude `-`; the optional
 * `-seq-<n>` suffix is matched from the end of the name.
 */
export function parseOrchEventName(event: string): OrchEventSubscription | null {
  const match = event.match(/^orch-events-(.+?)(?:-seq-(\d+))?$/);
  if (!match) return null;
  return {
    runId: match[1],
    afterSeq: match[2] ? parseInt(match[2], 10) : 0,
  };
}
