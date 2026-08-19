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
    body.forEach((_value) => {
      // forEach on FormData iterates (value, key); keys are collected via getAll below
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
      'session_compact',
      'session_fork',
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

  // M6 生态扩展: 用量面板路由 (settings GeneralTab → usageApi → GET /api/v1/usage)
  it('usage_summary is GET /api/v1/usage (M6 usage panel)', () => {
    const r = COMMAND_ROUTES.usage_summary;
    expect(r, 'missing route for usage_summary').toBeDefined();
    expect(r.method).toBe('GET');
    expect(r.path({})).toBe('/api/v1/usage');
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

  // M4: session engineering — compact + fork
  it('builds session_compact as POST /api/v1/sessions/{sessionId}/compact', () => {
    const r = COMMAND_ROUTES.session_compact;
    expect(r.method).toBe('POST');
    expect(r.path({ sessionId: 's/1' })).toBe('/api/v1/sessions/s%2F1/compact');
  });

  it('builds session_fork as POST /api/v1/sessions/{sessionId}/fork', () => {
    const r = COMMAND_ROUTES.session_fork;
    expect(r.method).toBe('POST');
    expect(r.path({ sessionId: 's/1' })).toBe('/api/v1/sessions/s%2F1/fork');
  });

  it('session_fork body maps camelCase args to backend snake_case fields', () => {
    const r = COMMAND_ROUTES.session_fork;
    expect(r.body).toBeDefined();
    // 完整参数
    expect(r.body!({ sessionId: 's1', atMessageId: 'm-9', title: '分支' })).toEqual({
      at_message_id: 'm-9',
      title: '分支',
    });
    // 缺省参数不下发（sessionId 走 path 不进 body）
    expect(r.body!({ sessionId: 's1' })).toEqual({});
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

  it('builds orchestration_create_lane as POST /api/v1/orchestration/lanes (M5)', () => {
    const r = COMMAND_ROUTES.orchestration_create_lane;
    expect(r.method).toBe('POST');
    // Guard: fixed collection path, no args interpolated.
    expect(r.path({})).toBe('/api/v1/orchestration/lanes');
    expect(r.path({ goal: 'x', agent: 'researcher' })).toBe('/api/v1/orchestration/lanes');
  });
});

// PR-C §5.4: memory IPC bridge 补全。memoryApi.ts(前端)调 invoke('search_memory'|'save_memory'),
// 但 commands.ts 没映射 → 前端 404。后端端点 backend/api/legacy_routes.py:2479 (POST /memory/search)
// + :2490 (POST /memory/save) 已存在, 补 IPC 桥即可。
describe('memory IPC routes (PR-C §5.4)', () => {
  it('has search_memory route posting to /api/v1/memory/search', () => {
    const r = COMMAND_ROUTES.search_memory;
    expect(r).toBeDefined();
    expect(r.method).toBe('POST');
    expect(r.path({})).toBe('/api/v1/memory/search');
  });

  it('search_memory body forwards query/memoryType/limit (with default 20)', () => {
    const r = COMMAND_ROUTES.search_memory;
    // Default limit = 20 when caller omits it
    expect(r.body!({ query: 'pasta' })).toEqual({
      query: 'pasta',
      memory_type: undefined,
      limit: 20,
    });
    // Caller-provided limit preserved
    expect(r.body!({ query: 'pasta', memoryType: 'episodic', limit: 5 })).toEqual({
      query: 'pasta',
      memory_type: 'episodic',
      limit: 5,
    });
  });

  it('has save_memory route posting to /api/v1/memory/save', () => {
    const r = COMMAND_ROUTES.save_memory;
    expect(r).toBeDefined();
    expect(r.method).toBe('POST');
    expect(r.path({})).toBe('/api/v1/memory/save');
  });

  it('save_memory body forwards content/memoryType/importance/tags', () => {
    const r = COMMAND_ROUTES.save_memory;
    expect(
      r.body!({
        content: 'user prefers dark mode',
        memoryType: 'semantic',
        importance: 7,
        tags: ['pref', 'ui'],
      }),
    ).toEqual({
      content: 'user prefers dark mode',
      memory_type: 'semantic',
      importance: 7,
      tags: ['pref', 'ui'],
    });
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
    expect(r.path({ key: 'current_session_id' })).toBe('/api/v1/preferences/current_session_id');
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

describe('permission IPC routes (M1 tool security hardening)', () => {
  // Backend: backend/api/permission_routes.py — GET /permissions/pending +
  // POST /permissions/{request_id}/answer（ApprovalAnswerBody extra="forbid"）。

  it('has permissions_pending route: GET /api/v1/permissions/pending', () => {
    const r = COMMAND_ROUTES.permissions_pending;
    expect(r).toBeDefined();
    expect(r.method).toBe('GET');
    expect(r.path({})).toBe('/api/v1/permissions/pending');
    expect(r.body).toBeUndefined();
  });

  it('has permissions_answer route: POST with url-encoded requestId path param', () => {
    const r = COMMAND_ROUTES.permissions_answer;
    expect(r).toBeDefined();
    expect(r.method).toBe('POST');
    expect(r.path({ requestId: 'abc-123' })).toBe('/api/v1/permissions/abc-123/answer');
    // 路径参数必须 url-encode（与 get_session / workspace_bind 同约定）
    expect(r.path({ requestId: 'id/with slash' })).toBe(
      '/api/v1/permissions/id%2Fwith%20slash/answer',
    );
  });

  // Guard: 后端 ApprovalAnswerBody 是 extra="forbid" — requestId 泄漏进 body
  // 会触发 422。body selector 必须只保留 approved/remember。
  it('permissions_answer body selector strips requestId (only approved/remember)', () => {
    const r = COMMAND_ROUTES.permissions_answer;
    expect(r.body).toBeDefined();
    expect(r.body!({ requestId: 'r-1', approved: true, remember: false, extraField: 'x' })).toEqual(
      { approved: true, remember: false },
    );
  });

  it('permission routes use /api/v1 prefix (防 404 guard)', () => {
    const paths = [
      COMMAND_ROUTES.permissions_pending.path({}),
      COMMAND_ROUTES.permissions_answer.path({ requestId: 'x' }),
    ];
    paths.forEach((p) => expect(p).toMatch(/^\/api\/v1\//));
  });
});

describe('question IPC routes (M2 part B: AskUserQuestion)', () => {
  // Backend: backend/api/question_routes.py — GET /questions/pending +
  // POST /questions/{request_id}/answer（QuestionAnswerBody extra="forbid"）。

  it('has questions_pending route: GET /api/v1/questions/pending', () => {
    const r = COMMAND_ROUTES.questions_pending;
    expect(r).toBeDefined();
    expect(r.method).toBe('GET');
    expect(r.path({})).toBe('/api/v1/questions/pending');
    expect(r.body).toBeUndefined();
  });

  it('has questions_answer route: POST with url-encoded requestId path param', () => {
    const r = COMMAND_ROUTES.questions_answer;
    expect(r).toBeDefined();
    expect(r.method).toBe('POST');
    expect(r.path({ requestId: 'abc-123' })).toBe('/api/v1/questions/abc-123/answer');
    // 路径参数必须 url-encode（与 permissions_answer / get_session 同约定）
    expect(r.path({ requestId: 'id/with slash' })).toBe(
      '/api/v1/questions/id%2Fwith%20slash/answer',
    );
  });

  // Guard: 后端 QuestionAnswerBody 是 extra="forbid" — requestId 泄漏进 body
  // 会触发 422。body selector 必须只保留 answers/custom。
  it('questions_answer body selector strips requestId (only answers/custom)', () => {
    const r = COMMAND_ROUTES.questions_answer;
    expect(r.body).toBeDefined();
    expect(
      r.body!({ requestId: 'r-1', answers: ['PDF'], custom: 'x', extraField: 'boom' }),
    ).toEqual({ answers: ['PDF'], custom: 'x' });
  });

  it('questions_answer body selector normalizes missing answers/custom', () => {
    const r = COMMAND_ROUTES.questions_answer;
    // Escape 空提交 → answers 缺失归一为 [], custom 缺失归一为 null
    expect(r.body!({ requestId: 'r-1' })).toEqual({ answers: [], custom: null });
  });

  it('question routes use /api/v1 prefix (防 404 guard)', () => {
    const paths = [
      COMMAND_ROUTES.questions_pending.path({}),
      COMMAND_ROUTES.questions_answer.path({ requestId: 'x' }),
    ];
    paths.forEach((p) => expect(p).toMatch(/^\/api\/v1\//));
  });
});

describe('MCP management IPC routes (M3)', () => {
  it('exposes status / servers / add / update / delete', () => {
    expect(COMMAND_ROUTES.mcp_status.method).toBe('GET');
    expect(COMMAND_ROUTES.mcp_status.path({})).toBe('/api/v1/mcp/status');
    expect(COMMAND_ROUTES.mcp_servers.method).toBe('GET');
    expect(COMMAND_ROUTES.mcp_servers.path({})).toBe('/api/v1/mcp/servers');
    expect(COMMAND_ROUTES.mcp_server_add.method).toBe('POST');
    expect(COMMAND_ROUTES.mcp_server_add.path({})).toBe('/api/v1/mcp/servers');
    expect(COMMAND_ROUTES.mcp_server_update.method).toBe('PATCH');
    expect(COMMAND_ROUTES.mcp_server_delete.method).toBe('DELETE');
  });

  it('mcp_server_update puts name in path and only patch fields in body', () => {
    const r = COMMAND_ROUTES.mcp_server_update;
    expect(r.path({ name: 'srv/1' })).toBe('/api/v1/mcp/servers/srv%2F1');
    // name must not leak into the body (backend model is extra=forbid)
    expect(r.body!({ name: 'srv', enabled: false, timeout_seconds: 45 })).toEqual({
      enabled: false,
      timeout_seconds: 45,
    });
    expect(r.body!({ name: 'srv', enabled: true })).toEqual({ enabled: true });
  });

  it('mcp_server_delete encodes the server name', () => {
    expect(COMMAND_ROUTES.mcp_server_delete.path({ name: 'drawio' })).toBe(
      '/api/v1/mcp/servers/drawio',
    );
    expect(COMMAND_ROUTES.mcp_server_delete.path({ name: 'a b' })).toBe(
      '/api/v1/mcp/servers/a%20b',
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

describe('agent_* IPC commands', () => {
  it('registers all five agent commands with /api/v1-prefixed paths', () => {
    const required = ['list_agents', 'get_agent', 'update_agent', 'toggle_agent', 'create_agent'];
    for (const cmd of required) {
      const route = COMMAND_ROUTES[cmd];
      expect(route).toBeDefined();
      // path 签名统一 (args: Record<string, unknown>) => string —— 传 { id: 'test' }
      //（list/create 的实现忽略参数）
      expect(route.path({ id: 'test' })).toMatch(/^\/api\/v1\//);
    }
  });

  it('strips id from update_agent body (extra=forbid)', () => {
    const route = COMMAND_ROUTES['update_agent'];
    expect(route.path({ id: 'x' })).toBe('/api/v1/agents/x');
    expect(route.body?.({ id: 'x', update: { systemPrompt: 'p' } })).toEqual({
      systemPrompt: 'p',
    });
  });

  it('strips id from toggle_agent body', () => {
    const route = COMMAND_ROUTES['toggle_agent'];
    expect(route.path({ id: 'x' })).toBe('/api/v1/agents/x/toggle');
    expect(route.body?.({ id: 'x', enabled: false })).toEqual({ enabled: false });
  });

  // ===== Wave 2 P1-4/P1-5: orchestration run lifecycle (2026-08-14) =====
  it('orchestration_list_runs is GET /api/v1/orch/runs with limit param', () => {
    const route = COMMAND_ROUTES['orchestration_list_runs'];
    expect(route.method).toBe('GET');
    expect(route.path({ params: { limit: 5 } })).toBe('/api/v1/orch/runs?limit=5');
    expect(route.path({})).toBe('/api/v1/orch/runs?limit=50');
  });

  it('orchestration_get_run is GET /api/v1/orch/runs/{run_id} (url-encoded)', () => {
    const route = COMMAND_ROUTES['orchestration_get_run'];
    expect(route.method).toBe('GET');
    expect(route.path({ run_id: 'orch-abc' })).toBe('/api/v1/orch/runs/orch-abc');
    expect(route.path({ run_id: 'a/b' })).toBe('/api/v1/orch/runs/a%2Fb');
  });

  it('orchestration_resume_run is POST /api/v1/orch/runs/{run_id}/resume', () => {
    const route = COMMAND_ROUTES['orchestration_resume_run'];
    expect(route.method).toBe('POST');
    expect(route.path({ run_id: 'orch-abc' })).toBe('/api/v1/orch/runs/orch-abc/resume');
  });

  it('orchestration_cancel_run is POST /api/v1/orch/runs/{run_id}/cancel (PR C C1)', () => {
    const route = COMMAND_ROUTES['orchestration_cancel_run'];
    expect(route.method).toBe('POST');
    expect(route.path({ run_id: 'orch-abc' })).toBe('/api/v1/orch/runs/orch-abc/cancel');
  });

  it('orchestration_update_plan is POST /api/v1/orch/runs/{run_id}/plan with plan body', () => {
    const route = COMMAND_ROUTES['orchestration_update_plan'];
    expect(route.method).toBe('POST');
    expect(route.path({ run_id: 'orch-abc' })).toBe('/api/v1/orch/runs/orch-abc/plan');
    const plan = [{ task_id: 't1', agent_id: 'primary', goal: 'g' }];
    expect(route.body?.({ run_id: 'orch-abc', plan })).toEqual({ plan });
  });
});
