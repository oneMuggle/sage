/**
 * IPC command → backend HTTP route mapping for Electron main process.
 *
 * Pure module (no electron imports) so it can be unit-tested with vitest
 * without spinning up the Electron runtime.
 */
export interface CommandRoute {
  method: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  path: (args: Record<string, unknown>) => string;
  isSse?: boolean;
}

export const COMMAND_ROUTES: Record<string, CommandRoute> = {
  // chat
  // I2: create + attach split — POST 立即返回 {streamId} 启动后台 LLM 调用,
  // GET attach 到同一 stream 拉取 NDJSON 事件。LLM 只跑一次。
  agent_chat_stream: { method: 'POST', path: () => '/chat/stream' },
  attach_chat_stream: {
    method: 'GET',
    path: (a) => `/chat/stream/${encodeURIComponent(String(a.streamId))}`,
  },
  interrupt_agent: { method: 'POST', path: () => '/interrupt' },

  // sessions
  list_sessions: {
    method: 'GET',
    path: (a) => {
      const limit = (a?.limit as number) ?? 100;
      const offset = (a?.offset as number) ?? 0;
      return `/sessions?limit=${limit}&offset=${offset}`;
    },
  },
  create_session: { method: 'POST', path: () => '/sessions' },
  get_session: { method: 'GET', path: (a) => `/sessions/${encodeURIComponent(String(a.id))}` },
  delete_session: {
    method: 'DELETE',
    path: (a) => `/sessions/${encodeURIComponent(String(a.id))}`,
  },

  // messages
  get_messages: {
    method: 'GET',
    path: (a) => {
      const id = encodeURIComponent(String(a.sessionId));
      const limit = (a?.limit as number) ?? 100;
      const offset = (a?.offset as number) ?? 0;
      return `/sessions/${id}/messages?limit=${limit}&offset=${offset}`;
    },
  },
  delete_message: {
    method: 'POST',
    path: (a) => `/messages/${encodeURIComponent(String(a.id))}/delete`,
  },

  // memory
  delete_memory: { method: 'POST', path: () => '/memory/delete' },

  // evolution
  trigger_evolution: { method: 'POST', path: () => '/evolution/trigger' },
};

export class UnknownIpcCommandError extends Error {
  constructor(cmd: string) {
    super(
      `Unknown IPC command: ${cmd}. ` +
        `See electron/commands.ts COMMAND_ROUTES for the supported set.`,
    );
    this.name = 'UnknownIpcCommandError';
  }
}
