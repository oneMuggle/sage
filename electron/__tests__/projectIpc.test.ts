import { beforeEach, describe, expect, it, vi } from 'vitest';

import { registerProjectIpc, type ProjectIpcDeps } from '../projectIpc';

type Handler = (event: unknown, payload?: unknown) => Promise<unknown>;

const handlers = new Map<string, Handler>();

function makeDeps(overrides: Partial<ProjectIpcDeps> = {}): ProjectIpcDeps {
  const deps = {
    register: (channel: string, handler: unknown) => handlers.set(channel, handler as Handler),
    fetch: vi.fn(),
    shell: { openPath: vi.fn().mockResolvedValue(''), showItemInFolder: vi.fn() },
    isDirectory: vi.fn(() => true),
    isTrusted: vi.fn(() => true),
    backendUrl: 'http://127.0.0.1:8765',
    getToken: () => 'test-token',
    ...overrides,
  };
  return deps as ProjectIpcDeps;
}

function okLocation(path = '/tmp/demo') {
  return { ok: true, status: 200, json: async () => ({ id: 'p1', path }) };
}

describe('projectIpc', () => {
  beforeEach(() => {
    handlers.clear();
  });

  it('opens the resolved project folder', async () => {
    const deps = makeDeps();
    (deps.fetch as ReturnType<typeof vi.fn>).mockResolvedValue(okLocation());
    registerProjectIpc(deps);

    const result = await handlers.get('project:open-folder')?.({}, { projectId: 'p1' });

    expect(deps.fetch).toHaveBeenCalledWith(
      'http://127.0.0.1:8765/api/v1/projects/p1/location',
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: 'Bearer test-token' }),
      }),
    );
    expect(deps.shell.openPath).toHaveBeenCalledWith('/tmp/demo');
    expect(result).toEqual({ success: true });
  });

  it('reveals the resolved project folder', async () => {
    const deps = makeDeps();
    (deps.fetch as ReturnType<typeof vi.fn>).mockResolvedValue(okLocation('/tmp/demo'));
    registerProjectIpc(deps);

    await handlers.get('project:reveal-folder')?.({}, { projectId: 'p1' });

    expect(deps.shell.showItemInFolder).toHaveBeenCalledWith('/tmp/demo');
  });

  it('rejects untrusted senders', async () => {
    const deps = makeDeps({ isTrusted: vi.fn(() => false) });
    registerProjectIpc(deps);

    const result = await handlers.get('project:open-folder')?.({}, { projectId: 'p1' });

    expect(result).toEqual({ error: '未授权的窗口请求' });
    expect(deps.fetch).not.toHaveBeenCalled();
    expect(deps.shell.openPath).not.toHaveBeenCalled();
  });

  it('maps backend 410 to a user-facing error', async () => {
    const deps = makeDeps();
    (deps.fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: false,
      status: 410,
      json: async () => ({ detail: { code: 'project_path_missing' } }),
    });
    registerProjectIpc(deps);

    const result = await handlers.get('project:open-folder')?.({}, { projectId: 'p1' });

    expect(result).toEqual({ error: '项目目录不存在或已被移动' });
    expect(deps.shell.openPath).not.toHaveBeenCalled();
  });

  it('rejects non-directory paths returned by the backend', async () => {
    const deps = makeDeps({ isDirectory: vi.fn(() => false) });
    (deps.fetch as ReturnType<typeof vi.fn>).mockResolvedValue(okLocation('/tmp/demo'));
    registerProjectIpc(deps);

    const result = await handlers.get('project:open-folder')?.({}, { projectId: 'p1' });

    expect(result).toEqual({ error: '项目目录不存在或已被移动' });
  });

  it('requires a projectId', async () => {
    const deps = makeDeps();
    registerProjectIpc(deps);

    const result = await handlers.get('project:open-folder')?.({}, {});

    expect(result).toEqual({ error: '缺少 projectId' });
  });
});
