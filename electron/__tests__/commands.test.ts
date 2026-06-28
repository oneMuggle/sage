import { describe, expect, it } from 'vitest';
import { COMMAND_ROUTES, UnknownIpcCommandError } from '../commands';

// Backend mounts legacy_routes under /api/v1 (see backend/main.py:215).
// All Electron IPC paths MUST match — otherwise every IPC call 404s.

describe('COMMAND_ROUTES', () => {
  it('includes the full session/message/chat surface used by the renderer', () => {
    const required = [
      'agent_chat_stream',
      'attach_chat_stream',
      'interrupt_agent',
      'list_sessions',
      'create_session',
      'delete_session',
      'get_messages',
      'delete_message',
    ];
    for (const cmd of required) {
      expect(COMMAND_ROUTES[cmd], `missing route for ${cmd}`).toBeDefined();
    }
  });

  // Guard: every command path MUST start with /api/v1 or /api/theme.
  // Legacy routes use /api/v1 (matches backend/main.py:215 legacy_router mount).
  // Theme routes use /api/theme (matches backend/main.py theme_router mount).
  // If a new command is added without one of these prefixes, this test fails —
  // preventing a class of 404 bugs where the renderer talks to a path the
  // backend doesn't expose at root.
  it('all command paths are prefixed with /api/v1 or /api/theme', () => {
    for (const [cmd, route] of Object.entries(COMMAND_ROUTES)) {
      const samplePath = route.path({
        limit: 1,
        offset: 0,
        id: 'x',
        streamId: 'x',
        sessionId: 'x',
      });
      expect(samplePath, `${cmd} path must start with /api/v1 or /api/theme`).toMatch(
        /^(\/api\/v1\/|\/api\/theme\/)/,
      );
    }
  });

  // I2: agent_chat_stream 改为同步 create(JSON 立即返回 streamId),不再是 SSE
  it('agent_chat_stream is now plain POST /api/v1/chat/stream (not SSE)', () => {
    const r = COMMAND_ROUTES.agent_chat_stream;
    expect(r.method).toBe('POST');
    expect(r.path({})).toBe('/api/v1/chat/stream');
    expect(r.isSse).toBeUndefined();
  });

  it('attach_chat_stream is GET with streamId as path param (url-encoded)', () => {
    const r = COMMAND_ROUTES.attach_chat_stream;
    expect(r.method).toBe('GET');
    expect(r.path({ streamId: 'sid/1' })).toBe('/api/v1/chat/stream/sid%2F1');
    expect(r.path({ streamId: 'abc-123' })).toBe('/api/v1/chat/stream/abc-123');
  });

  it('builds list_sessions URL with limit/offset query params', () => {
    const path = COMMAND_ROUTES.list_sessions.path({ limit: 50, offset: 10 });
    expect(path).toBe('/api/v1/sessions?limit=50&offset=10');
  });

  it('defaults list_sessions limit/offset to 100/0', () => {
    expect(COMMAND_ROUTES.list_sessions.path({})).toBe('/api/v1/sessions?limit=100&offset=0');
  });

  it('builds get_messages URL with sessionId encoded', () => {
    const path = COMMAND_ROUTES.get_messages.path({ sessionId: 's/1' });
    expect(path).toBe('/api/v1/sessions/s%2F1/messages?limit=100&offset=0');
  });

  it('builds create_session as POST /api/v1/sessions', () => {
    expect(COMMAND_ROUTES.create_session.method).toBe('POST');
    expect(COMMAND_ROUTES.create_session.path({})).toBe('/api/v1/sessions');
  });

  it('builds get_session as GET /api/v1/sessions/{id} (url-encoded)', () => {
    const r = COMMAND_ROUTES.get_session;
    expect(r.method).toBe('GET');
    expect(r.path({ id: 's/1' })).toBe('/api/v1/sessions/s%2F1');
  });

  it('builds delete_session as DELETE /api/v1/sessions/{id}', () => {
    const r = COMMAND_ROUTES.delete_session;
    expect(r.method).toBe('DELETE');
    expect(r.path({ id: 'abc' })).toBe('/api/v1/sessions/abc');
  });

  it('builds delete_message as POST /api/v1/messages/{id}/delete', () => {
    const r = COMMAND_ROUTES.delete_message;
    expect(r.method).toBe('POST');
    expect(r.path({ id: 'm1' })).toBe('/api/v1/messages/m1/delete');
  });

  it('builds interrupt_agent as POST /api/v1/interrupt', () => {
    expect(COMMAND_ROUTES.interrupt_agent.path({})).toBe('/api/v1/interrupt');
  });

  it('builds delete_memory as POST /api/v1/memory/delete', () => {
    expect(COMMAND_ROUTES.delete_memory.path({})).toBe('/api/v1/memory/delete');
  });

  it('builds trigger_evolution as POST /api/v1/evolution/trigger', () => {
    expect(COMMAND_ROUTES.trigger_evolution.path({})).toBe('/api/v1/evolution/trigger');
  });
});

describe('settings & preferences IPC routes', () => {
  it('has get_settings route', () => {
    expect(COMMAND_ROUTES.get_settings).toBeDefined();
    expect(COMMAND_ROUTES.get_settings.method).toBe('GET');
    expect(COMMAND_ROUTES.get_settings.path({})).toBe('/api/v1/settings');
  });

  it('has set_settings route', () => {
    expect(COMMAND_ROUTES.set_settings).toBeDefined();
    expect(COMMAND_ROUTES.set_settings.method).toBe('PUT');
    expect(COMMAND_ROUTES.set_settings.path({})).toBe('/api/v1/settings');
  });

  it('has get_preference route with key encoding', () => {
    const r = COMMAND_ROUTES.get_preference;
    expect(r.method).toBe('GET');
    expect(r.path({ key: 'theme_mode' })).toBe('/api/v1/preferences/theme_mode');
    expect(r.path({ key: 'has space' })).toBe('/api/v1/preferences/has%20space');
  });

  it('has set_preference route with key encoding', () => {
    const r = COMMAND_ROUTES.set_preference;
    expect(r.method).toBe('PUT');
    expect(r.path({ key: 'current_session_id' })).toBe(
      '/api/v1/preferences/current_session_id',
    );
  });

  it('all settings/preference paths have /api/v1 prefix', () => {
    // 防止漏前缀导致 404
    const paths = [
      COMMAND_ROUTES.get_settings.path({}),
      COMMAND_ROUTES.set_settings.path({}),
      COMMAND_ROUTES.get_preference.path({ key: 'theme_mode' }),
      COMMAND_ROUTES.set_preference.path({ key: 'theme_mode' }),
    ];
    paths.forEach((p) => expect(p).toMatch(/^\/api\/v1\//));
  });
});

describe('theme IPC routes', () => {
  it('has theme_list route (GET /api/theme/list)', () => {
    const r = COMMAND_ROUTES.theme_list;
    expect(r).toBeDefined();
    expect(r.method).toBe('GET');
    expect(r.path({})).toBe('/api/theme/list');
  });

  it('has theme_save route (POST /api/theme/save)', () => {
    const r = COMMAND_ROUTES.theme_save;
    expect(r).toBeDefined();
    expect(r.method).toBe('POST');
    expect(r.path({})).toBe('/api/theme/save');
  });

  it('has theme_get route (GET /api/theme/get/{id}) with URL encoding', () => {
    const r = COMMAND_ROUTES.theme_get;
    expect(r).toBeDefined();
    expect(r.method).toBe('GET');
    expect(r.path({ id: 'abc-123' })).toBe('/api/theme/get/abc-123');
    expect(r.path({ id: 'id/with/slash' })).toBe('/api/theme/get/id%2Fwith%2Fslash');
  });

  it('has theme_delete route (POST /api/theme/delete)', () => {
    const r = COMMAND_ROUTES.theme_delete;
    expect(r).toBeDefined();
    expect(r.method).toBe('POST');
    expect(r.path({})).toBe('/api/theme/delete');
  });

  it('all theme paths have /api/theme prefix', () => {
    const paths = [
      COMMAND_ROUTES.theme_list.path({}),
      COMMAND_ROUTES.theme_save.path({}),
      COMMAND_ROUTES.theme_get.path({ id: 'x' }),
      COMMAND_ROUTES.theme_delete.path({}),
    ];
    paths.forEach((p) => expect(p).toMatch(/^\/api\/theme\//));
  });
});

describe('scheduled tasks IPC routes', () => {
  it('has scheduled_list_tasks route', () => {
    expect(COMMAND_ROUTES.scheduled_list_tasks).toEqual({
      method: 'GET',
      path: expect.any(Function),
    });
    expect(COMMAND_ROUTES.scheduled_list_tasks.path({})).toBe('/api/v1/scheduled/tasks');
  });

  it('has scheduled_create_task route', () => {
    expect(COMMAND_ROUTES.scheduled_create_task.method).toBe('POST');
    expect(COMMAND_ROUTES.scheduled_create_task.path({})).toBe('/api/v1/scheduled/tasks');
  });

  it('has scheduled_update_task route with id encoding', () => {
    expect(COMMAND_ROUTES.scheduled_update_task.method).toBe('PATCH');
    expect(COMMAND_ROUTES.scheduled_update_task.path({ id: 'task-1' })).toBe(
      '/api/v1/scheduled/tasks/task-1',
    );
  });

  it('has scheduled_delete_task route', () => {
    expect(COMMAND_ROUTES.scheduled_delete_task.method).toBe('DELETE');
    expect(COMMAND_ROUTES.scheduled_delete_task.path({ id: 'task-1' })).toBe(
      '/api/v1/scheduled/tasks/task-1',
    );
  });

  it('has scheduled_run_task route', () => {
    expect(COMMAND_ROUTES.scheduled_run_task.method).toBe('POST');
    expect(COMMAND_ROUTES.scheduled_run_task.path({ id: 'task-1' })).toBe(
      '/api/v1/scheduled/tasks/task-1/run',
    );
  });
});

describe('UnknownIpcCommandError', () => {
  it('names the offending command and references the source of truth', () => {
    const err = new UnknownIpcCommandError('foo_bar');
    expect(err.message).toMatch(/foo_bar/);
    expect(err.message).toMatch(/COMMAND_ROUTES/);
    expect(err.name).toBe('UnknownIpcCommandError');
  });
});
