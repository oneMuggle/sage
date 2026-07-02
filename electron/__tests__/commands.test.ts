import { describe, expect, it, vi, beforeEach } from 'vitest';
import { COMMAND_ROUTES, UnknownIpcCommandError } from '../commands';

// ===== Skills IPC (Task 4: PR-C load-new) =====
//
// The skills IPC module (`electron/skillsIpc.ts`) is a pure module that
// takes an injected `register(channel, handler)` function so we can mock
// electron without booting the runtime. Tests assert that:
//   - all 3 channels are registered with the right name
//   - pick-files delegates to dialog.showOpenDialog + handles cancel
//   - rescan + import forward to backend via injected fetch
//   - import error response surfaces detail.type as message

// `vi.mock` is hoisted to the top of the file by Vitest — before any
// imports. The factory closure cannot reference top-level `const`s
// declared below (TDZ error). Use `vi.hoisted` to safely declare the
// shared mocks the factory references.
const mocks = vi.hoisted(() => ({
  dialog: { showOpenDialog: vi.fn() },
  BrowserWindow: { getFocusedWindow: vi.fn(() => null) },
  fs: { readFileSync: vi.fn() },
}));

vi.mock('electron', () => ({
  dialog: mocks.dialog,
  BrowserWindow: mocks.BrowserWindow,
}));

// Mock fs so the import handler doesn't hit the real filesystem when
// tests pass fake paths like '/path/a.md'. We include `__esModule: true`
// + `default` so Vitest's ESM/CJS interop doesn't trip on the partial
// mock — Node's fs is a CJS module and `import { readFileSync } from 'fs'`
// relies on Node's default-export interop.
vi.mock('fs', () => ({
  __esModule: true,
  default: { readFileSync: mocks.fs.readFileSync },
  readFileSync: mocks.fs.readFileSync,
}));

// Injectable register fn captures all ipcMain.handle calls.
const registeredHandlers = new Map<string, (...args: unknown[]) => unknown>();
function fakeRegister(channel: string, handler: (...args: unknown[]) => unknown): void {
  registeredHandlers.set(channel, handler);
}

// Provide a stubbed fetch the rescan/import handlers will pick up.
const mockFetch = vi.fn();

import { registerSkillsIpc } from '../skillsIpc';

describe('skills IPC (PR-C)', () => {
  beforeEach(() => {
    registeredHandlers.clear();
    mocks.dialog.showOpenDialog.mockReset();
    mocks.BrowserWindow.getFocusedWindow.mockReset();
    mocks.BrowserWindow.getFocusedWindow.mockReturnValue(null);
    mocks.fs.readFileSync.mockReset();
    mocks.fs.readFileSync.mockReturnValue(Buffer.from('# content'));
    mockFetch.mockReset();
    (global as unknown as { fetch: typeof mockFetch }).fetch = mockFetch;
    registerSkillsIpc(fakeRegister);
  });

  it('registers all 3 channels', () => {
    expect(registeredHandlers.has('skills:pick-files')).toBe(true);
    expect(registeredHandlers.has('skills:rescan')).toBe(true);
    expect(registeredHandlers.has('skills:import')).toBe(true);
  });

  it('pick-files returns paths from dialog', async () => {
    mocks.dialog.showOpenDialog.mockResolvedValue({
      canceled: false,
      filePaths: ['/path/a.md', '/path/b.md'],
    });
    const handler = registeredHandlers.get('skills:pick-files')!;
    const result = await handler({});
    expect(result).toEqual(['/path/a.md', '/path/b.md']);
    expect(mocks.dialog.showOpenDialog).toHaveBeenCalledTimes(1);
  });

  it('pick-files returns null on cancel', async () => {
    mocks.dialog.showOpenDialog.mockResolvedValue({ canceled: true, filePaths: [] });
    const handler = registeredHandlers.get('skills:pick-files')!;
    const result = await handler({});
    expect(result).toBeNull();
  });

  it('rescan POSTs to backend /api/v1/skills/rescan and returns JSON', async () => {
    const mockResponse = {
      loaded: [{ name: 'a', source: 'skillmd', path: '/p/a/SKILL.md' }],
      skipped: [],
      total_loaded: 1,
    };
    mockFetch.mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => mockResponse,
    });

    const handler = registeredHandlers.get('skills:rescan')!;
    const result = await handler({});

    expect(result).toEqual(mockResponse);
    expect(mockFetch).toHaveBeenCalledTimes(1);
    const [url, init] = mockFetch.mock.calls[0];
    expect(String(url)).toContain('/api/v1/skills/rescan');
    expect(init.method).toBe('POST');
  });

  it('rescan throws on non-OK HTTP response with status', async () => {
    mockFetch.mockResolvedValue({
      ok: false,
      status: 500,
      json: async () => ({ detail: { type: 'internal', message: 'boom' } }),
    });

    const handler = registeredHandlers.get('skills:rescan')!;
    await expect(handler({})).rejects.toThrow(/500/);
  });

  it('import posts multipart FormData with file blobs', async () => {
    mockFetch.mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        imported: [{ name: 'a', path: '/p/a/SKILL.md' }],
        skipped: [],
      }),
    });

    const handler = registeredHandlers.get('skills:import')!;
    const result = (await handler({}, ['/path/a.md'])) as {
      imported: Array<{ name: string; path: string }>;
      skipped: Array<{ name: string; reason: string }>;
    };

    expect(result.imported).toHaveLength(1);
    const [url, init] = mockFetch.mock.calls[0];
    expect(String(url)).toContain('/api/v1/skills/import');
    expect(init.method).toBe('POST');
    // body is a FormData instance with one 'files' entry
    const body = init.body as FormData;
    expect(body).toBeInstanceOf(FormData);
    const entries: string[][] = [];
    body.forEach((_value, key) => {
      // forEach on FormData iterates (value, key); we want the keys
      // (in case there are dupes) — collect via getAll below
      void _value;
    });
    const all = body.getAll('files');
    expect(all.length).toBe(1);
    expect(all[0]).toBeInstanceOf(Blob);
    void entries;
  });

  it('import handles 400 response with detail.type as error', async () => {
    mockFetch.mockResolvedValue({
      ok: false,
      status: 400,
      json: async () => ({ detail: { type: 'invalid_request', message: 'no files' } }),
    });

    const handler = registeredHandlers.get('skills:import')!;
    await expect(handler({}, ['/path/a.md'])).rejects.toThrow(/invalid_request/);
  });

  it('import handles 500 response with detail.type as error', async () => {
    mockFetch.mockResolvedValue({
      ok: false,
      status: 500,
      json: async () => ({ detail: { type: 'no_skills_dir', message: 'cannot create' } }),
    });

    const handler = registeredHandlers.get('skills:import')!;
    await expect(handler({}, ['/path/a.md'])).rejects.toThrow(/no_skills_dir/);
  });
});

// Backend mounts legacy_routes under /api/v1 (see backend/main.py:215).
// All Electron IPC paths MUST match — otherwise every IPC call 404s.
const API_PREFIX = '/api/v1';

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

  // Guard: every command path MUST start with /api/v1 (matches backend mount).
  // If a new command is added without the prefix, this test fails — preventing
  // a class of 404 bugs where the renderer talks to a path the backend doesn't
  // expose at root.
  it('all command paths are prefixed with /api/v1', () => {
    for (const [cmd, route] of Object.entries(COMMAND_ROUTES)) {
      const samplePath = route.path({
        limit: 1,
        offset: 0,
        id: 'x',
        streamId: 'x',
        sessionId: 'x',
      });
      expect(samplePath, `${cmd} path must start with ${API_PREFIX}`).toMatch(
        new RegExp(`^${API_PREFIX}/`),
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

describe('UnknownIpcCommandError', () => {
  it('names the offending command and references the source of truth', () => {
    const err = new UnknownIpcCommandError('foo_bar');
    expect(err.message).toMatch(/foo_bar/);
    expect(err.message).toMatch(/COMMAND_ROUTES/);
    expect(err.name).toBe('UnknownIpcCommandError');
  });
});
