import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('../desktopInvoke', () => ({
  invoke: vi.fn(),
}));

import { invoke } from '../desktopInvoke';
import { orchestrationClient } from '../orchestrationClient';

const invokeMock = invoke as unknown as ReturnType<typeof vi.fn>;

describe('orchestrationClient', () => {
  afterEach(() => {
    invokeMock.mockReset();
  });

  it('createLane() invokes orchestration_create_lane with the goal payload', async () => {
    const fixture = { ok: true, team_id: 'team-1', lanes: [], tasks: [] };
    invokeMock.mockResolvedValueOnce(fixture);

    const result = await orchestrationClient.createLane({ goal: 'research X' });

    expect(invokeMock).toHaveBeenCalledWith('orchestration_create_lane', { goal: 'research X' });
    expect(result).toEqual(fixture);
  });

  it('createLane() forwards an explicit agent', async () => {
    invokeMock.mockResolvedValueOnce({ ok: true, team_id: 't', lanes: [], tasks: [] });

    await orchestrationClient.createLane({ goal: 'g', agent: 'researcher' });

    expect(invokeMock).toHaveBeenCalledWith('orchestration_create_lane', {
      goal: 'g',
      agent: 'researcher',
    });
  });

  it('listLanes() still invokes orchestration_list_lanes', async () => {
    invokeMock.mockResolvedValueOnce([]);
    await orchestrationClient.listLanes({});
    expect(invokeMock).toHaveBeenCalledWith('orchestration_list_lanes', { params: {} });
  });

  describe('getBoard (P2-5)', () => {
    const fixture = {
      schema_version: '1.0',
      generated_at: 1758500000000,
      generated_by: 'http-api',
      active: [],
      blocked: [],
      finished: [],
      freshness_summary: { total: 0, fresh: 0, stale: 0, dead: 0, overall_level: 'fresh' },
    };

    it('defaults to view=ops_full', async () => {
      invokeMock.mockResolvedValueOnce(fixture);
      const result = await orchestrationClient.getBoard();
      expect(invokeMock).toHaveBeenCalledWith('orchestration_board', { view: 'ops_full' });
      expect(result).toEqual(fixture);
    });

    it('forwards ui_minimal projection envelope', async () => {
      const envelope = {
        parent_content_hash: 'abc123',
        parent_schema_version: 'board@1.0',
        view: 'ui_minimal',
        entries: [{ lane_id: 'lane-1', task_id: 'task-1', status: 'running' }],
        downgrade_for_compatibility: [],
        redaction_provenance: { agent_id: 'field not in accepted_field_families' },
      };
      invokeMock.mockResolvedValueOnce(envelope);
      const result = await orchestrationClient.getBoard('ui_minimal');
      expect(invokeMock).toHaveBeenCalledWith('orchestration_board', { view: 'ui_minimal' });
      // 返回形态透传 —— ui_minimal 是投影信封，不含快照分组字段。
      expect(result).toEqual(envelope);
      expect(result.parent_content_hash).toBe('abc123');
      expect(Array.isArray(result.entries)).toBe(true);
      expect(result.redaction_provenance).toHaveProperty('agent_id');
    });

    it('propagates IPC failure (caller decides degradation)', async () => {
      invokeMock.mockRejectedValueOnce(new Error('ipc down'));
      await expect(orchestrationClient.getBoard()).rejects.toThrow('ipc down');
    });
  });
});
