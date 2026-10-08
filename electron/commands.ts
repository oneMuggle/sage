/**
 * IPC command → backend HTTP route mapping for Electron main process.
 *
 * Pure module (no electron imports) so it can be unit-tested with vitest
 * without spinning up the Electron runtime.
 */
import { DOMAIN_ROUTES } from './commandRoutes';

export interface CommandRoute {
  method: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  path: (args: Record<string, unknown>) => string;
  body?: (args: Record<string, unknown>) => Record<string, unknown>;
  isSse?: boolean;
  /**
   * Skip the camelCase→snake_case body translation. For payloads whose
   * keys are user-defined data rather than JS identifiers — e.g. MCP
   * server `env` maps, where `PATH` would be mangled into `_p_a_t_h`.
   * Callers must send snake_case top-level keys themselves.
   */
  rawBody?: boolean;
}


export const COMMAND_ROUTES: Record<string, CommandRoute> = {
  ...DOMAIN_ROUTES, // electron/commandRoutes/*: add new commands there, not in this file
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

/**
 * Module-level Map: streamId → AbortController.
 *
 * Tracks in-flight streaming IPC commands (e.g. `wiki_chat_stream`) so the
 * renderer can abort the backend HTTP request via `sage:unlisten` when it
 * unsubscribes. The controller is created when the stream starts and
 * removed in the `finally` block of the relay loop on normal completion,
 * error, or abort. Read by main.ts on `sage:unlisten`.
 */
export const streamControllers = new Map<string, AbortController>();

