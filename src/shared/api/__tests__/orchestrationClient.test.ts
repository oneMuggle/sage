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
});
