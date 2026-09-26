/** Update-only network boundary. Never applies to loopback backend requests. */
import type { RequestInit, Response } from 'node-fetch';

import { fetchCompat } from '../fetchCompat';

export function updateDeploymentMode(): 'online' | 'intranet' | 'offline' {
  const value = (process.env.SAGE_DEPLOYMENT_MODE ?? '').trim().toLowerCase();
  if (!value || value === 'online') return 'online';
  return value === 'intranet' ? 'intranet' : 'offline';
}

function assertUpdateUrl(url: string): void {
  const mode = updateDeploymentMode();
  if (mode === 'offline') throw new Error('Updates disabled by offline deployment policy');
  if (mode !== 'intranet') return;
  const destination = new URL(url);
  const allowed = (process.env.SAGE_UPDATE_ALLOWED_ORIGINS ?? '').split(',').filter((s) => s.trim()).map((s) => {
    const origin = new URL(s.trim());
    if (origin.protocol !== 'https:' || origin.username || origin.password || origin.pathname !== '/' || origin.search || origin.hash) {
      throw new Error('Invalid administrator update origin; network denied');
    }
    return origin.origin;
  });
  if (destination.protocol !== 'https:' || destination.username || destination.password || !allowed.includes(destination.origin)) {
    throw new Error('Update origin not approved by administrator');
  }
}

/** Deadline covers headers AND body, even when a transport ignores cancellation. */
export async function fetchUpdate(url: string, init: RequestInit = {}, timeoutMs = 30_000): Promise<Response> {
  assertUpdateUrl(url);
  const controller = new AbortController();
  const external = init.signal;
  let rejectDeadline: (reason: Error) => void = () => {};
  const deadline = new Promise<never>((_resolve, reject) => { rejectDeadline = reject; });
  // HEAD/error responses have no body consumer; never leave an unhandled rejection.
  void deadline.catch(() => {});
  const cancel = () => {
    controller.abort();
    rejectDeadline(new Error('Update request cancelled'));
  };
  const timer = setTimeout(() => {
    controller.abort();
    rejectDeadline(new Error('Update request timed out'));
  }, timeoutMs);
  timer.unref?.();
  const cleanup = () => {
    clearTimeout(timer);
    external?.removeEventListener('abort', cancel);
  };
  external?.addEventListener('abort', cancel, { once: true });
  if (external?.aborted) {
    cancel();
    cleanup();
    throw new Error('Update request cancelled');
  }
  try {
    const response = await Promise.race([
      fetchCompat(url, { ...init, signal: controller.signal, ...(updateDeploymentMode() === 'intranet' ? { redirect: 'error' as const } : {}) }),
      deadline,
    ]);
    if (init.method === 'HEAD' || !response.ok) cleanup();
    return new Proxy(response, {
      get(target, key) {
        const value = Reflect.get(target, key, target);
        if (['json', 'text', 'arrayBuffer', 'buffer'].includes(String(key)) && typeof value === 'function') {
          return async () => {
            try { return await Promise.race([value.call(target), deadline]); }
            finally { cleanup(); }
          };
        }
        return typeof value === 'function' ? value.bind(target) : value;
      },
    });
  } catch (error) {
    cleanup();
    throw error;
  }
}
