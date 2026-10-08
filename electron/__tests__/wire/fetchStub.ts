import { vi } from 'vitest';

/**
 * The one `node-fetch` stand-in the wire tests install through
 * `vi.mock('node-fetch', ...)`. It lives in its own module so that the mock factory can import it
 * without importing the harness (which imports electron/invoke.ts, which imports node-fetch).
 */
export const wireFetch = vi.fn();
