/**
 * Minimal ambient declarations for `eventsource@2.0.2` (the SSE client used
 * by the memory relay in `main.ts`).
 *
 * The 2.x line is Node http/https-based (no `fetch` dependency — required
 * because Electron 21 main / Node 16 has no global `fetch`), but it ships
 * no `.d.ts` (only 3.x/4.x do, and those hard-depend on `globalThis.fetch`).
 * We therefore declare exactly the surface the relay uses: construct, the
 * three event-handler properties, `readyState` and `close()`.
 *
 * NOTE: `@types/eventsource` on npm is a deprecated *stub* that points back
 * at the package's own types — it does not help 2.0.2 — so a local ambient
 * module is the correct fix.
 */

declare module 'eventsource' {
  interface MessageEventLike {
    data: string;
  }

  class EventSource {
    static readonly CONNECTING: 0;
    static readonly OPEN: 1;
    static readonly CLOSED: 2;

    constructor(url: string, eventSourceInitDict?: { headers?: Record<string, string> });

    readonly readyState: number;
    onopen: ((event: MessageEventLike) => void) | null;
    onmessage: ((event: MessageEventLike) => void) | null;
    onerror: ((event: MessageEventLike) => void) | null;
    close(): void;
  }

  // eventsource@2.0.2 is CommonJS `module.exports = EventSource` (the class
  // itself, no `.default` / no `__esModule`). A named `import { EventSource }`
  // would emit `require('eventsource').EventSource` → undefined at runtime;
  // a default import is interop-wrapped by esModuleInterop's __importDefault.
  export default EventSource;
}
