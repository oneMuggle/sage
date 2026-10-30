import { describe, expect, it, vi } from 'vitest';

import {
  AgentBrowserBridge,
  startAgentBrowserBridge,
  type BridgeDeps,
  type BridgeWindow,
} from '../agentBrowserBridge';

interface FakeWindow extends BridgeWindow {
  destroyed: boolean;
  visible: boolean;
  debuggerCommands: Array<{ method: string; params?: Record<string, unknown> }>;
  url: string;
}

function makeWindow(visible: boolean): FakeWindow {
  const state: FakeWindow = {
    destroyed: false,
    visible,
    debuggerCommands: [],
    url: 'about:blank',
    show: vi.fn(),
    close() {
      state.destroyed = true;
    },
    isDestroyed: () => state.destroyed,
    webContents: {
      debugger: {
        attach: vi.fn(),
        sendCommand: vi.fn(async (method: string, params?: Record<string, unknown>) => {
          state.debuggerCommands.push({ method, params });
          return { method };
        }),
      },
      getURL: () => state.url,
      getTitle: () => 'Sage 浏览器',
      getUserAgent: () => 'Mozilla/5.0 Chrome/106.0.0.0 Safari/537.36',
      loadURL: vi.fn(async (url: string) => {
        state.url = url;
      }),
      capturePage: vi.fn(async () => ({
        toPNG: () => Buffer.from('png-bytes'),
      })),
      isDestroyed: () => state.destroyed,
    },
  };
  return state;
}

function makeDeps(cookieStore: Record<string, unknown>[] = [], failLoad = false) {
  const windows: FakeWindow[] = [];
  let counter = 0;
  const deps: BridgeDeps & { windows: FakeWindow[]; cookieStore: Record<string, unknown>[] } = {
    windows,
    cookieStore,
    createWindow: (visible: boolean) => {
      const win = makeWindow(visible);
      if (failLoad) {
        win.webContents.loadURL = vi.fn(async () => {
          throw new Error('ERR_NAME_NOT_RESOLVED');
        });
      }
      windows.push(win);
      return win;
    },
    getSession: () => ({
      cookies: {
        get: async () => cookieStore as never,
        set: async (details: Record<string, unknown>) => {
          cookieStore.push(details);
        },
      },
    }),
    randomId: () => `t${++counter}`,
    log: () => undefined,
  };
  return deps;
}

describe('AgentBrowserBridge', () => {
  it('keeps headless and visible targets isolated', async () => {
    const deps = makeDeps();
    const bridge = new AgentBrowserBridge(deps);

    const headless = await bridge.dispatch({
      method: 'Target.createTarget',
      params: { url: 'https://hidden.example/' },
      headless: true,
    });
    const visible = await bridge.dispatch({
      method: 'Target.createTarget',
      params: { url: 'https://visible.example/' },
      headless: false,
    });

    expect((headless as { targetId: string }).targetId).not.toBe(
      (visible as { targetId: string }).targetId,
    );
    expect(deps.windows.map((win) => win.visible)).toEqual([false, true]);

    const headlessList = await bridge.dispatch({ method: 'Target.getTargets', headless: true });
    const visibleList = await bridge.dispatch({ method: 'Target.getTargets', headless: false });
    expect(headlessList).toEqual({
      targetInfos: [expect.objectContaining({ url: 'https://hidden.example/', type: 'page' })],
    });
    expect(visibleList).toEqual({
      targetInfos: [expect.objectContaining({ url: 'https://visible.example/', type: 'page' })],
    });
  });

  it('attaches a page and forwards Page/Runtime commands to its debugger', async () => {
    const deps = makeDeps();
    const bridge = new AgentBrowserBridge(deps);
    const created = (await bridge.dispatch({
      method: 'Target.createTarget',
      params: { url: 'about:blank' },
      headless: true,
    })) as { targetId: string };

    const attached = (await bridge.dispatch({
      method: 'Target.attachToTarget',
      params: { targetId: created.targetId },
      headless: true,
    })) as { sessionId: string };
    expect(attached.sessionId).toBe(`sage-${created.targetId}`);

    await bridge.dispatch({
      method: 'Page.navigate',
      params: { url: 'https://example.com/' },
      targetId: created.targetId,
      headless: true,
    });
    await bridge.dispatch({
      method: 'Runtime.evaluate',
      params: { expression: '1+1', returnByValue: true },
      targetId: created.targetId,
      headless: true,
    });

    const commands = deps.windows[0].debuggerCommands.map((entry) => entry.method);
    expect(commands).toEqual(['Page.navigate', 'Runtime.evaluate']);
  });

  it('maps Electron cookies to CDP shape and back', async () => {
    const deps = makeDeps([
      {
        name: 'SID',
        value: 'v',
        domain: '.example.com',
        path: '/',
        secure: true,
        httpOnly: true,
        expirationDate: 1800000000,
        sameSite: 'lax',
      },
    ]);
    const bridge = new AgentBrowserBridge(deps);

    const got = (await bridge.dispatch({
      method: 'Storage.getCookies',
      headless: false,
    })) as { cookies: Array<Record<string, unknown>> };
    expect(got.cookies[0]).toMatchObject({
      name: 'SID',
      domain: '.example.com',
      secure: true,
      sameSite: 'Lax',
      expires: 1800000000,
    });

    await bridge.dispatch({
      method: 'Storage.setCookies',
      params: {
        cookies: [
          {
            name: 'T',
            value: '1',
            domain: '.example.com',
            path: '/',
            secure: true,
            sameSite: 'None',
            expires: 1900000000,
          },
        ],
      },
      headless: false,
    });
    const stored = deps.cookieStore[deps.cookieStore.length - 1];
    expect(stored).toMatchObject({
      name: 'T',
      value: '1',
      domain: '.example.com',
      url: 'https://example.com/',
      sameSite: 'no_restriction',
      expirationDate: 1900000000,
    });
  });

  it('captures screenshots via capturePage', async () => {
    const deps = makeDeps();
    const bridge = new AgentBrowserBridge(deps);
    await bridge.dispatch({
      method: 'Target.createTarget',
      params: { url: 'about:blank' },
      headless: true,
    });
    const shot = (await bridge.dispatch({
      method: 'Page.captureScreenshot',
      params: { format: 'png' },
      headless: true,
    })) as { data: string };
    expect(Buffer.from(shot.data, 'base64').toString()).toBe('png-bytes');
  });

  it('rejects unknown browser-level methods', async () => {
    const bridge = new AgentBrowserBridge(makeDeps());
    await expect(
      bridge.dispatch({ method: 'Browser.crashEverything', headless: false }),
    ).rejects.toThrow('unsupported method');
  });

  it('isolates targets by backend session id', async () => {
    const deps = makeDeps();
    const bridge = new AgentBrowserBridge(deps);
    const a = (await bridge.dispatch({
      method: 'Target.createTarget',
      params: { url: 'https://a.example/' },
      headless: false,
      session: 'session-a',
    })) as { targetId: string };
    await bridge.dispatch({
      method: 'Target.createTarget',
      params: { url: 'https://b.example/' },
      headless: false,
      session: 'session-b',
    });

    const aTargets = (await bridge.dispatch({
      method: 'Target.getTargets',
      headless: false,
      session: 'session-a',
    })) as { targetInfos: Array<{ url: string }> };
    expect(aTargets.targetInfos.map((info) => info.url)).toEqual(['https://a.example/']);

    await expect(
      bridge.dispatch({
        method: 'Target.attachToTarget',
        params: { targetId: a.targetId },
        headless: false,
        session: 'session-b',
      }),
    ).rejects.toThrow('unknown targetId');
  });

  it('attaches the target specified in params, not the first one', async () => {
    const deps = makeDeps();
    const bridge = new AgentBrowserBridge(deps);
    const first = (await bridge.dispatch({
      method: 'Target.createTarget',
      params: { url: 'https://first.example/' },
      headless: true,
      session: 's1',
    })) as { targetId: string };
    const second = (await bridge.dispatch({
      method: 'Target.createTarget',
      params: { url: 'https://second.example/' },
      headless: true,
      session: 's1',
    })) as { targetId: string };

    const attached = (await bridge.dispatch({
      method: 'Target.attachToTarget',
      params: { targetId: second.targetId },
      headless: true,
      session: 's1',
    })) as { sessionId: string };
    expect(attached.sessionId).toContain(second.targetId);
    expect(attached.sessionId).not.toContain(first.targetId);
  });

  it('recycles the window when the initial navigation fails', async () => {
    const deps = makeDeps([], true);
    const bridge = new AgentBrowserBridge(deps);
    await expect(
      bridge.dispatch({
        method: 'Target.createTarget',
        params: { url: 'https://unreachable.example/' },
        headless: true,
        session: 's1',
      }),
    ).rejects.toThrow('ERR_NAME_NOT_RESOLVED');
    expect(deps.windows[0].destroyed).toBe(true);
    const list = (await bridge.dispatch({
      method: 'Target.getTargets',
      headless: true,
      session: 's1',
    })) as { targetInfos: unknown[] };
    expect(list.targetInfos).toHaveLength(0);
  });

  it('rejects non-http(s) target urls', async () => {
    const bridge = new AgentBrowserBridge(makeDeps());
    await expect(
      bridge.dispatch({
        method: 'Target.createTarget',
        params: { url: 'file:///etc/passwd' },
        headless: true,
      }),
    ).rejects.toThrow('unsupported url scheme');
  });
});

describe('startAgentBrowserBridge', () => {
  it('requires the token header and dispatches commands over HTTP', async () => {
    const handle = await startAgentBrowserBridge(makeDeps(), { token: 'secret-token' });
    try {
      const base = `http://127.0.0.1:${handle.port}/command`;
      const unauthorized = await fetch(base, {
        method: 'POST',
        body: JSON.stringify({ method: 'Target.getTargets' }),
      });
      expect(unauthorized.status).toBe(401);

      const ok = await fetch(base, {
        method: 'POST',
        headers: { 'x-sage-bridge-token': 'secret-token' },
        body: JSON.stringify({ method: 'Target.getTargets', headless: true }),
      });
      expect(ok.status).toBe(200);
      expect(await ok.json()).toEqual({ result: { targetInfos: [] } });

      const bad = await fetch(base, {
        method: 'POST',
        headers: { 'x-sage-bridge-token': 'secret-token' },
        body: JSON.stringify({ method: 'Nope.method', headless: true }),
      });
      const payload = (await bad.json()) as { error?: { message: string } };
      expect(payload.error?.message).toContain('unsupported method');
    } finally {
      await handle.close();
    }
  });
});
