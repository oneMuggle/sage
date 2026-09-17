import { describe, expect, it } from 'vitest';
import { parseOrchEventName } from '../eventRouting';

describe('parseOrchEventName', () => {
  it('parses a plain runId without seq suffix', () => {
    expect(parseOrchEventName('orch-events-team01')).toEqual({
      runId: 'team01',
      afterSeq: 0,
    });
  });

  it('parses a runId containing hyphens (backend run_id formats)', () => {
    // legacy_routes: run_id = f"orch-{uuid4()}"
    expect(
      parseOrchEventName('orch-events-orch-550e8400-e29b-41d4-a716-446655440000'),
    ).toEqual({
      runId: 'orch-550e8400-e29b-41d4-a716-446655440000',
      afterSeq: 0,
    });
    // orchestration_router: run_id = f"api-{team_id}", team_id = f"team-{hex12}"
    expect(parseOrchEventName('orch-events-api-team-a1b2c3d4e5f6')).toEqual({
      runId: 'api-team-a1b2c3d4e5f6',
      afterSeq: 0,
    });
  });

  it('parses the -seq-N suffix appended after a hyphenated runId', () => {
    expect(
      parseOrchEventName('orch-events-orch-550e8400-e29b-41d4-a716-446655440000-seq-42'),
    ).toEqual({
      runId: 'orch-550e8400-e29b-41d4-a716-446655440000',
      afterSeq: 42,
    });
    expect(parseOrchEventName('orch-events-api-team-a1b2c3d4e5f6-seq-7')).toEqual({
      runId: 'api-team-a1b2c3d4e5f6',
      afterSeq: 7,
    });
  });

  it('parses -seq-0 and rejects non-matching names', () => {
    expect(parseOrchEventName('orch-events-run1-seq-0')).toEqual({
      runId: 'run1',
      afterSeq: 0,
    });
    expect(parseOrchEventName('chat-stream-abc123')).toBeNull();
    expect(parseOrchEventName('orch-events-')).toBeNull();
  });
});
