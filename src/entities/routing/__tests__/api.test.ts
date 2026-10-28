import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const backendRequest = vi.hoisted(() => vi.fn());

vi.mock('../../../shared/api/backendRequest', () => ({ backendRequest }));

import { routeModel } from '../api';

describe('routing API client', () => {
  beforeEach(() => {
    backendRequest.mockResolvedValue({ selected_model: {}, reason: 'r', alternatives: [] });
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it('posts the full routing request to /api/v1/routing/route', async () => {
    await routeModel({
      task_type: 'code_generation',
      context_length: 8000,
      required_capabilities: ['chat'],
      endpoint_id: 'ep-a',
      user_preference: { preferred_tier: 'balanced' },
    });

    expect(backendRequest).toHaveBeenCalledWith({
      path: '/api/v1/routing/route',
      method: 'POST',
      body: {
        task_type: 'code_generation',
        context_length: 8000,
        required_capabilities: ['chat'],
        endpoint_id: 'ep-a',
        user_preference: { preferred_tier: 'balanced' },
      },
    });
  });

  it('omits unset optional fields instead of sending nulls', async () => {
    await routeModel({ task_type: 'chat', context_length: 4096, required_capabilities: [] });

    const argument = backendRequest.mock.calls[0][0];
    expect(argument.body).toEqual({
      task_type: 'chat',
      context_length: 4096,
      required_capabilities: [],
    });
    expect('endpoint_id' in argument.body).toBe(false);
    expect('user_preference' in argument.body).toBe(false);
  });
});
