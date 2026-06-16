/**
 * Pure NDJSON relay between FastAPI backend and Electron renderer.
 *
 * Extracted from electron/main.ts so it can be unit-tested without
 * spinning up the Electron runtime.
 *
 * Flow (I2: create + attach split, 避免 LLM 被调两次):
 *   1. main process receives ipcMain.handle('sage:invoke', 'agent_chat_stream', args)
 *      → POSTs args to backend /chat/stream → 立即拿到 {streamId}
 *   2. renderer subscribes via listen('chat-stream-{streamId}', handler)
 *   3. main process opens relay: GET /chat/stream/{streamId}, parses NDJSON,
 *      webContents.send for each event
 *
 * 注意: 整个 chat 流只有一次 LLM 调用,发生在 step 1 create 时。
 * step 3 attach 只是从后端已有的 stream queue 拉取事件,不会再触发 LLM。
 *
 * Why node-fetch (not global `fetch`):
 *   Electron 21 bundles Node 16.13.1 — no global fetch.
 *   See electron/invoke.ts for the same rationale.
 *
 * Why Node ReadableStream (not Web ReadableStream):
 *   node-fetch@2 returns a Node `Readable` from `res.body`, not a Web
 *   `ReadableStream`. `Readable.toWeb()` (Web stream adapter) is Node 17+,
 *   so we consume Node streams directly with `.on('data' / 'end')`.
 */

import fetch from 'node-fetch';
import type { Readable } from 'node:stream';

export type WebContentsLike = {
  send: (channel: string, payload: unknown) => void;
};

/**
 * Iterate over a Node Readable stream with NDJSON body, invoking
 * `onEvent` for each parsed line. Honors AbortSignal.
 *
 * The `body` parameter is typed as `NodeJS.ReadableStream | null` to match
 * what `@types/node-fetch` declares for `Response.body`. At runtime in Node
 * 16 / Electron 21, both node-fetch@2's body and `Readable.from()` return a
 * Node `Readable` (with `.destroy()`, `.setEncoding()`, `.on('data')`).
 * We cast through `unknown` to call those Node-stream methods.
 */
export async function parseNdjsonStream(
  body: NodeJS.ReadableStream | null,
  onEvent: (event: unknown) => void,
  signal?: AbortSignal,
): Promise<void> {
  if (!body) return;
  const stream = body as unknown as Readable;
  if (signal?.aborted) {
    stream.destroy();
    return;
  }

  return new Promise<void>((resolve) => {
    let buffer = '';
    let settled = false;
    const finish = () => {
      if (settled) return;
      settled = true;
      signal?.removeEventListener('abort', onAbort);
      resolve();
    };
    const onAbort = () => {
      stream.destroy();
      // 'close'/'error' will fire after destroy and call finish()
    };
    signal?.addEventListener('abort', onAbort, { once: true });

    stream.setEncoding('utf8');
    stream.on('data', (chunk: unknown) => {
      buffer += String(chunk);
      const lines = buffer.split('\n');
      buffer = lines.pop() ?? '';
      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed) continue;
        try {
          onEvent(JSON.parse(trimmed));
        } catch {
          onEvent({ raw: trimmed });
        }
      }
    });
    stream.on('end', finish);
    stream.on('close', finish);
    stream.on('error', (e: unknown) => {
      // Aborting the underlying fetch surfaces as ERR_STREAM_PREMATURE_CLOSE
      // (Node 16) or AbortError on the body. Neither is a real error for us.
      const err = e as { name?: string; code?: string } | null;
      if (err?.name === 'AbortError' || err?.code === 'ERR_STREAM_PREMATURE_CLOSE') {
        finish();
        return;
      }
      finish();
    });
  });
}

/**
 * Attach to an existing chat stream (I2) and forward events to the renderer.
 *
 * 与旧版的差异:
 *   - 旧: POST /chat/stream with args → 再次触发 LLM (重复调用)
 *   - 新: GET /chat/stream/{streamId} → 拉取后端 queue 中的事件,不再触发 LLM
 */
export async function relayChatStream(
  webContents: WebContentsLike,
  eventName: string,
  streamId: string,
  backendUrl: string,
  signal: AbortSignal,
): Promise<void> {
  let res: import('node-fetch').Response;
  try {
    res = await fetch(`${backendUrl}/chat/stream/${encodeURIComponent(streamId)}`, {
      method: 'GET',
      headers: { Accept: 'application/x-ndjson' },
      signal,
    });
  } catch (e) {
    if (e instanceof Error && e.name === 'AbortError') return;
    // 其它网络错误静默吞掉,不要把 main 进程炸了
    return;
  }

  if (!res.ok) return;

  await parseNdjsonStream(
    res.body,
    (event) => {
      webContents.send(`sage:event:${eventName}`, event);
    },
    signal,
  );
}
