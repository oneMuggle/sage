import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const backendRequest = vi.hoisted(() => vi.fn());

vi.mock('../../shared/api/backendRequest', () => ({
  backendRequest,
}));

import { deleteOverride, getDiff, listModels } from './api';

describe('model catalog API client', () => {
  beforeEach(() => {
    backendRequest.mockResolvedValue({});
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it('serializes endpoint_id and encodes model catalog path segments', async () => {
    await listModels({ endpointId: 'endpoint/a?b', limit: 10, offset: 20 });
    expect(backendRequest).toHaveBeenCalledWith({
      path: '/api/v1/model-catalog/models?limit=10&offset=20&endpoint_id=endpoint%2Fa%3Fb',
      method: 'GET',
    });

    await getDiff('snapshot/a?b');
    expect(backendRequest).toHaveBeenLastCalledWith({
      path: '/api/v1/model-catalog/snapshots/snapshot%2Fa%3Fb/diff',
      method: 'GET',
    });
  });

  it('sends the expected revision in delete override query parameters', async () => {
    await deleteOverride('endpoint/a', 'model/a?b', 7);
    expect(backendRequest).toHaveBeenCalledWith({
      path: '/api/v1/model-catalog/overrides?endpoint_id=endpoint%2Fa&model_id=model%2Fa%3Fb&expected_revision=7',
      method: 'DELETE',
    });
  });
});
