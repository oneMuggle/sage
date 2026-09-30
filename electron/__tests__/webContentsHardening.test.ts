import { describe, expect, it, vi } from 'vitest';

import {
  hardenWebContents,
  installWebContentsHardening,
  SANDBOXED_POPUP,
  type WebContentsLike,
  type WindowOpenResult,
} from '../webContentsHardening';

function fakeContents(session?: unknown) {
  const listeners: Record<string, (e: { preventDefault(): void }) => void> = {};
  let handler: ((d: { url: string }) => WindowOpenResult) | undefined;
  const contents: WebContentsLike = {
    session,
    on: (event, listener) => {
      listeners[event] = listener;
      return contents;
    },
    setWindowOpenHandler: (h) => {
      handler = h;
    },
  };
  return {
    contents,
    attachWebview: () => {
      const preventDefault = vi.fn();
      listeners['will-attach-webview']({ preventDefault });
      return preventDefault;
    },
    open: (url: string) => handler!({ url }),
  };
}

describe('webContentsHardening', () => {
  it('blocks every <webview> attach (GHSA-9qh4)', () => {
    const f = fakeContents();
    hardenWebContents(f.contents, { openExternal: vi.fn() });
    expect(f.attachWebview()).toHaveBeenCalledTimes(1);
  });

  it('denies popups by default and hands the url to openExternal (GHSA-gr2m / hq2x)', () => {
    const openExternal = vi.fn();
    const f = fakeContents();
    hardenWebContents(f.contents, { openExternal });
    expect(f.open('https://example.com')).toEqual({ action: 'deny' });
    expect(openExternal).toHaveBeenCalledWith('https://example.com');
  });

  it('allows only locked-down http(s) popups for opted-in sessions', () => {
    const openExternal = vi.fn();
    const arena = {};
    const f = fakeContents(arena);
    hardenWebContents(f.contents, {
      openExternal,
      allowsSandboxedPopups: (c) => c.session === arena,
    });
    expect(f.open('https://login.example.com')).toBe(SANDBOXED_POPUP);
    expect(f.open('file:///C:/secret')).toEqual({ action: 'deny' });
    expect(openExternal).toHaveBeenCalledWith('file:///C:/secret');
  });

  it('installs itself on web-contents-created and survives handler errors', () => {
    let listener: ((e: unknown, c: WebContentsLike) => void) | undefined;
    const warn = vi.fn();
    installWebContentsHardening({ on: (_e, l) => ((listener = l), undefined) }, {
      openExternal: vi.fn(),
      warn,
    });
    const f = fakeContents();
    listener!({}, f.contents);
    expect(f.attachWebview()).toHaveBeenCalled();

    const broken = {
      on: () => {
        throw new Error('boom');
      },
      setWindowOpenHandler: vi.fn(),
    } as unknown as WebContentsLike;
    expect(() => listener!({}, broken)).not.toThrow();
    expect(warn).toHaveBeenCalledWith('security: hardenWebContents failed', expect.any(Object));
  });
});
