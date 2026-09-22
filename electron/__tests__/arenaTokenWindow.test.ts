// electron/__tests__/arenaTokenWindow.test.ts
// Stubs every effect (BrowserWindow / fetch / sleep / clock / session) so the
// controller's decision logic runs without Electron — same seam style as
// logIpc.test.ts (fake register map) plus the module's own injectable seams.
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { BrowserWindow } from 'electron';
import {
  ArenaTokenWindowController,
  defaultCreateWindow,
  plainChromeUa,
  registerArenaTokenWindow,
} from '../arenaTokenWindow';

// vi.mock factories are hoisted above every const — mocks shared with test
// bodies must come from vi.hoisted (vitest docs: "Cannot access before init").
const { setProxyMock, setUserAgentMock, appOnMock } = vi.hoisted(() => ({
  setProxyMock: vi.fn(async () => undefined),
  setUserAgentMock: vi.fn(),
  appOnMock: vi.fn(),
}));

vi.mock('electron', () => ({
  app: { on: appOnMock },
  BrowserWindow: vi.fn(),
  session: {
    fromPartition: () => ({ setProxy: setProxyMock, setUserAgent: setUserAgentMock }),
  },
}));

const TOKEN = 'x'.repeat(2000);

interface FakeWindow {
  loaded: string[];
  destroyed: boolean;
  vars: Record<string, unknown>;
  mintCalls: number;
  mintFailuresRemaining: number;
  grecaptcha: boolean;
  loadURL: (url: string) => Promise<void>;
  reload: () => void;
  destroy: () => void;
  isDestroyed: () => boolean;
  webContents: { executeJavaScript: (code: string, gesture?: boolean) => Promise<unknown> };
}

function makeFakeWindow(): FakeWindow {
  const win: FakeWindow = {
    loaded: [],
    destroyed: false,
    vars: {},
    mintCalls: 0,
    mintFailuresRemaining: 0,
    grecaptcha: true,
    async loadURL(url) {
      win.loaded.push(url);
    },
    reload() {
      win.grecaptcha = true; // reload revives grecaptcha
    },
    destroy() {
      win.destroyed = true;
    },
    isDestroyed() {
      return win.destroyed;
    },
    webContents: {
      async executeJavaScript(code) {
        if (code.includes('document.readyState')) return win.grecaptcha;
        if (code.includes('window.grecaptcha')) return win.grecaptcha;
        if (code === 'navigator.userAgent') return 'FakeUA/21.4.4';
        if (code.includes('grecaptcha.enterprise.ready')) {
          win.mintCalls += 1;
          if (win.mintFailuresRemaining > 0) {
            win.mintFailuresRemaining -= 1;
            win.vars.__tok = null;
            win.vars.__err = 'recaptcha error';
          } else {
            win.vars.__tok = TOKEN;
            win.vars.__err = null;
          }
          return undefined;
        }
        if (code.includes("fetch('https://api.ipify.org")) {
          win.vars.__ip = '203.0.113.7';
          return undefined;
        }
        if (code.startsWith('window.__tok')) return win.vars.__tok ?? null;
        if (code.startsWith('window.__err')) return win.vars.__err ?? null;
        if (code.startsWith('window.__ip')) return win.vars.__ip ?? null;
        return undefined;
      },
    },
  };
  return win;
}

interface FetchCall {
  url: string;
  init: Record<string, unknown>;
}

interface HarnessOverrides {
  win?: FakeWindow;
}

function makeHarness(overrides: HarnessOverrides = {}) {
  const win = overrides.win ?? makeFakeWindow();
  const fetchCalls: FetchCall[] = [];
  const delays: number[] = [];
  // state responses are consumed in order; the last one is repeated
  const stateQueue: Array<Record<string, unknown>> = [];
  const pushResults: Array<{ ok: boolean; status: number }> = [];
  let pushCalls = 0;

  const fetchJson = vi.fn(async (url: string, init: Record<string, unknown>) => {
    fetchCalls.push({ url, init });
    if (url.endsWith('/token-window/state')) {
      const next = stateQueue.length > 1 ? stateQueue.shift() : stateQueue[0] ?? {};
      return { ok: true, status: 200, json: next };
    }
    if (url.endsWith('/token-window/push')) {
      pushCalls += 1;
      const result = pushResults[pushCalls - 1] ?? { ok: true, status: 200 };
      if (result.ok) return { ok: true, status: 200, json: { ok: true, age_sec: 0 } };
      return { ok: false, status: result.status, json: { detail: 'err' } };
    }
    return { ok: false, status: 404, json: undefined };
  });

  const controller = new ArenaTokenWindowController({
    backendUrl: 'http://127.0.0.1:8790',
    authToken: () => 'cap-token',
    createWindow: () => win,
    sessionFromPartition: () => ({ setProxy: setProxyMock }),
    fetchJson,
    // MUST actually wait: pollLoop with an instant delay spins without
    // yielding and grows the call arrays unboundedly (heap OOM).
    delay: async (ms: number) => {
      delays.push(ms);
      if (ms > 0) await new Promise((r) => setTimeout(r, ms));
    },
    ...overrides,
  });
  // pushCalls is a primitive — expose it as a getter or callers hold a stale 0
  return {
    controller, win, fetchCalls, fetchJson, delays, stateQueue, pushResults,
    pushCount: () => pushCalls,
  };
}

function stateEnabled(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    enabled: true,
    needed: false,
    reject_count: 0,
    want_proxy: false,
    proxy_url: '',
    poll_interval_sec: 0.5,
    ...overrides,
  };
}

beforeEach(() => {
  setProxyMock.mockClear();
  appOnMock.mockClear();
});

describe('ArenaTokenWindowController', () => {
  it('start: loads arena, warms up, pushes token with Bearer auth', async () => {
    const h = makeHarness();
    h.stateQueue.push(stateEnabled());
    await h.controller.start();

    expect(h.win.loaded[0]).toBe('https://arena.ai/agent/');
    expect(h.win.mintCalls).toBe(1);
    expect(h.pushCount()).toBe(1);
    const push = h.fetchCalls.find((c) => c.url.endsWith('/token-window/push'))!;
    expect(push.init.headers).toMatchObject({ Authorization: 'Bearer cap-token' });
    const body = JSON.parse(push.init.body as string) as Record<string, unknown>;
    expect(body.token).toBe(TOKEN);
    expect(body.exit_ip).toBe('203.0.113.7');
    expect(body.ua).toBe('FakeUA/21.4.4');

    const status = h.controller.status();
    expect(status.ready).toBe(true);
    expect(status.count).toBe(1);
    expect(status.exitIp).toBe('203.0.113.7');
    expect(status.ua).toBe('FakeUA/21.4.4');
    await h.controller.stop();
  });

  it('state.needed triggers an on-demand mint (and clears via next poll)', async () => {
    const h = makeHarness();
    h.stateQueue.push(stateEnabled());
    await h.controller.start();
    expect(h.pushCount()).toBe(1); // warmup

    h.stateQueue.push(stateEnabled({ needed: true }));
    await vi.waitFor(() => expect(h.pushCount()).toBe(2), { timeout: 4000 });
    // needed=false afterwards → no further mints
    h.stateQueue.push(stateEnabled({ needed: false }));
    await h.controller.stop();
    const mintsAfterStop = h.win.mintCalls;
    await new Promise((r) => setTimeout(r, 20));
    expect(h.win.mintCalls).toBe(mintsAfterStop);
  });

  it('state.enabled=false destroys the window and stops the loop', async () => {
    const h = makeHarness();
    h.stateQueue.push(stateEnabled());
    await h.controller.start();
    h.stateQueue.push(stateEnabled({ enabled: false }));
    await vi.waitFor(() => expect(h.win.destroyed).toBe(true), { timeout: 4000 });
    expect(h.controller.status().running).toBe(false);
  });

  it('push failure retries with exponential backoff, then succeeds', async () => {
    const h = makeHarness();
    h.stateQueue.push(stateEnabled());
    h.pushResults.push({ ok: false, status: 502 }); // warmup push fails once
    await h.controller.start();

    await vi.waitFor(() => expect(h.pushCount()).toBe(2), { timeout: 4000 });
    expect(h.delays).toContain(1000); // first backoff step
    expect(h.controller.status().count).toBe(1);
    await h.controller.stop();
  });

  it('push 403 stops the window (disabled mid-flight)', async () => {
    const h = makeHarness();
    h.stateQueue.push(stateEnabled());
    h.pushResults.push({ ok: false, status: 403 });
    await h.controller.start();
    expect(h.pushCount()).toBe(1);
    await vi.waitFor(() => expect(h.controller.status().running).toBe(false), { timeout: 4000 });
    expect(h.win.destroyed).toBe(true);
  });

  it('mint failure reloads once and retries (ready-is-only-a-hint)', async () => {
    const h = makeHarness();
    h.win.mintFailuresRemaining = 1;
    h.stateQueue.push(stateEnabled());
    await h.controller.start();

    expect(h.win.mintCalls).toBe(2); // failed attempt + retry after reload
    expect(h.win.loaded.length).toBeGreaterThanOrEqual(2); // reload happened
    expect(h.pushCount()).toBe(1);
    expect(h.controller.status().count).toBe(1);
    await h.controller.stop();
  });

  it('pick-proxy applies credential-less proxies and rejects credentialed ones', async () => {
    const h = makeHarness();
    h.stateQueue.push(stateEnabled());
    await h.controller.start();

    await h.controller.pickProxy('http://127.0.0.1:3128');
    expect(setProxyMock).toHaveBeenCalledWith({ proxyRules: 'http://127.0.0.1:3128' });
    // applying a proxy reloads the page and warm-mints again
    expect(h.win.loaded.length).toBeGreaterThanOrEqual(2);
    expect(h.controller.status().proxyUrl).toBe('http://127.0.0.1:3128');

    await expect(h.controller.pickProxy('http://u:p@1.2.3.4:8080')).rejects.toThrow(
      /want_proxy/,
    );
    await h.controller.pickProxy(null);
    expect(setProxyMock).toHaveBeenLastCalledWith({ mode: 'system' });
    await h.controller.stop();
  });

  it('want_proxy from state applies the backend (relay) proxy once', async () => {
    const h = makeHarness();
    h.stateQueue.push(stateEnabled());
    await h.controller.start();
    expect(setProxyMock).not.toHaveBeenCalled();

    h.stateQueue.push(
      stateEnabled({ want_proxy: true, proxy_url: 'http://127.0.0.1:45678' }),
    );
    await vi.waitFor(
      () => expect(setProxyMock).toHaveBeenCalledWith({ proxyRules: 'http://127.0.0.1:45678' }),
      { timeout: 4000 },
    );
    const callsAfterApply = setProxyMock.mock.calls.length;
    // same proxy_url on later polls → no re-apply
    await new Promise((r) => setTimeout(r, 20));
    expect(setProxyMock.mock.calls.length).toBe(callsAfterApply);
    expect(h.controller.status().proxyUrl).toBe('http://127.0.0.1:45678');
    await h.controller.stop();
  });
});

describe('registerArenaTokenWindow', () => {
  it('wires the five channels and before-quit cleanup', async () => {
    const handlers = new Map<string, (...args: unknown[]) => unknown>();
    registerArenaTokenWindow({
      register: (channel, handler) => handlers.set(channel, handler),
      getBackendUrl: () => 'http://127.0.0.1:8790',
      getAuthToken: () => 'cap-token',
    });
    expect([...handlers.keys()].sort()).toEqual([
      'sage:arena-token:pick-proxy',
      'sage:arena-token:reload',
      'sage:arena-token:start',
      'sage:arena-token:status',
      'sage:arena-token:stop',
    ]);
    expect(appOnMock).toHaveBeenCalledWith('before-quit', expect.any(Function));

    const status = handlers.get('sage:arena-token:status')!() as ReturnType<
      ReturnType<typeof registerArenaTokenWindow>['status']
    >;
    expect(status.running).toBe(false);

    // pick-proxy handler unwraps (evt, payload) — invalid payload → system proxy
    const pickProxy = handlers.get('sage:arena-token:pick-proxy')!;
    await pickProxy({ sender: { id: 1 } }, { proxyUrl: null });
    expect(setProxyMock).toHaveBeenCalledWith({ mode: 'system' });
  });
});

describe('defaultCreateWindow UA normalization', () => {
  it('plainChromeUa strips the host app name/version and Electron tokens', () => {
    const raw =
      'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) ' +
      'arena-token-smoke/1.0.0 Chrome/106.0.5249.199 Electron/21.4.4 Safari/537.36';
    expect(plainChromeUa(raw)).toBe(
      'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) ' +
        'Chrome/106.0.5249.199 Safari/537.36',
    );
  });

  it('plainChromeUa leaves an already-clean Chrome UA untouched', () => {
    const clean =
      'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) ' +
      'Chrome/106.0.5249.199 Safari/537.36';
    expect(plainChromeUa(clean)).toBe(clean);
  });

  it('defaultCreateWindow normalizes the partition session UA before first load', () => {
    const raw =
      'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) ' +
      'sage/9.9.9 Chrome/106.0.5249.199 Electron/21.4.4 Safari/537.36';
    const fakeWin = {
      webContents: { getUserAgent: () => raw },
    };
    (BrowserWindow as unknown as ReturnType<typeof vi.fn>).mockImplementationOnce(
      () => fakeWin,
    );
    const win = defaultCreateWindow();
    expect(win).toBe(fakeWin as unknown as ReturnType<typeof defaultCreateWindow>);
    expect(setUserAgentMock).toHaveBeenCalledTimes(1);
    expect(setUserAgentMock).toHaveBeenCalledWith(
      'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) ' +
        'Chrome/106.0.5249.199 Safari/537.36',
    );
  });
});
