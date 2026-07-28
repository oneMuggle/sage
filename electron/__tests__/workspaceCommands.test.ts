import { describe, expect, it } from 'vitest';

import { COMMAND_ROUTES } from '../commands';

describe('workspace command routes', () => {
  it('binds a workspace with an encoded session id', () => {
    const route = COMMAND_ROUTES.workspace_bind;

    expect(route?.method).toBe('PUT');
    expect(route?.path({ sessionId: 's/a' })).toBe('/api/v1/sessions/s%2Fa/workspace');
  });

  it('gets a workspace binding with an encoded session id', () => {
    const route = COMMAND_ROUTES.workspace_get;

    expect(route?.method).toBe('GET');
    expect(route?.path({ sessionId: 's/a' })).toBe('/api/v1/sessions/s%2Fa/workspace');
  });

  it('revokes a workspace binding with an encoded session id', () => {
    const route = COMMAND_ROUTES.workspace_revoke;

    expect(route?.method).toBe('DELETE');
    expect(route?.path({ sessionId: 's/a' })).toBe('/api/v1/sessions/s%2Fa/workspace');
  });

  it('encodes session, query, and bounded limit', () => {
    const route = COMMAND_ROUTES.workspace_search_files;

    expect(route?.method).toBe('GET');
    expect(route?.path({ sessionId: 's/a', query: 'Q&A', limit: 20 })).toBe(
      '/api/v1/sessions/s%2Fa/workspace/files?q=Q%26A&limit=20',
    );
  });

  it('defaults and clamps workspace search limits to 1-50', () => {
    const route = COMMAND_ROUTES.workspace_search_files;

    expect(route?.path({ sessionId: 's', query: 'q' })).toBe(
      '/api/v1/sessions/s/workspace/files?q=q&limit=20',
    );
    expect(route?.path({ sessionId: 's', query: 'q', limit: 0 })).toBe(
      '/api/v1/sessions/s/workspace/files?q=q&limit=1',
    );
    expect(route?.path({ sessionId: 's', query: 'q', limit: 51 })).toBe(
      '/api/v1/sessions/s/workspace/files?q=q&limit=50',
    );
  });

  it('keeps the /api/v1 prefix for every workspace route', () => {
    const paths = [
      COMMAND_ROUTES.workspace_bind?.path({ sessionId: 's' }),
      COMMAND_ROUTES.workspace_get?.path({ sessionId: 's' }),
      COMMAND_ROUTES.workspace_revoke?.path({ sessionId: 's' }),
      COMMAND_ROUTES.workspace_search_files?.path({ sessionId: 's', query: 'q' }),
    ];

    paths.forEach((path) => expect(path).toMatch(/^\/api\/v1\//));
  });
});
