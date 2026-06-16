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
 */

export type WebContentsLike = {
  send: (channel: string, payload: unknown) => void;
};

/**
 * Iterate over a fetch Response with NDJSON body, invoking `onEvent`
 * for each parsed line. Honors AbortSignal.
 */
export async function parseNdjsonStream(
  res: Response,
  onEvent: (event: unknown) => void,
  signal?: AbortSignal,
): Promise<void> {
  if (!res.body) return;
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  try {
    while (true) {
      if (signal?.aborted) return;
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
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
    }
  } catch (e) {
    if (e instanceof Error && e.name === 'AbortError') return;
    throw e;
  }
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
  let res: Response;
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
    res,
    (event) => {
      webContents.send(`sage:event:${eventName}`, event);
    },
    signal,
  );
}
