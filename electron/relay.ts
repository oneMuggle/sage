/**
 * Pure SSE/NDJSON relay between FastAPI backend and Electron renderer.
 *
 * Extracted from electron/main.ts so it can be unit-tested without
 * spinning up the Electron runtime.
 *
 * Flow:
 *   1. main process receives ipcMain.handle('sage:invoke', 'agent_chat_stream', args)
 *      → POSTs args to backend /chat/stream
 *   2. renderer subscribes via listen('chat-stream-{streamId}', handler)
 *   3. main process opens an internal stream relay: POSTs the same args
 *      to /chat/stream, parses NDJSON, webContents.send for each event
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
 * Open a streaming chat connection and forward events to the renderer.
 *
 * Strategy: the backend's /chat/stream endpoint creates the stream
 * AND returns events in the same response. So we POST the chat args
 * directly and parse the NDJSON response.
 */
export async function relayChatStream(
  webContents: WebContentsLike,
  eventName: string,
  sessionId: string,
  args: Record<string, unknown>,
  backendUrl: string,
  signal: AbortSignal,
): Promise<void> {
  let res: Response;
  try {
    res = await fetch(`${backendUrl}/chat/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'application/x-ndjson' },
      body: JSON.stringify({ ...args, session_id: sessionId }),
      signal,
    });
  } catch (e) {
    if (e instanceof Error && e.name === 'AbortError') return;
    // 其它网络错误静默吞掉,不要把 main 进程炸了
    return;
  }

  if (!res.ok) return;

  await parseNdjsonStream(res, (event) => {
    webContents.send(`sage:event:${eventName}`, event);
  }, signal);
}
