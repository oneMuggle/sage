/**
 * Live deep spec: evolution logs reachability.
 *
 * Exercises the production evolution endpoint against a live backend
 * (port 8765). This is a route-reachability test — NOT a signal → draft
 * round-trip, because the round-trip is not exercisable live.
 *
 * Deviations from the brief, all binding per Task 12 ruling R10:
 *
 *   D1 — Brief requested a full signal → draft round-trip on
 *        `/api/v1/evolution/signals`, `/evolution/draft`,
 *        `/evolution/queue`, `/evolution/approve`. NONE of those four
 *        routes exist in the real backend. The ONLY evolution endpoint
 *        is `GET /api/v1/evolution/logs`
 *        (`legacy_routes.py:2380`) returning a
 *        `List[EvolutionLogResponse]`.
 *        The "signal → draft" pipeline is implemented as background
 *        workers wired by the codebase, not as HTTP endpoints, so it
 *        cannot be exercised from a Playwright test. This file is the
 *        closest live analog: confirm the public evolution surface
 *        (`/logs`) is mounted and reachable.
 *
 *   D2 — Brief's `signals.length >= 1` assertion does not exist
 *        because `/evolution/signals` 404s. We accept any of
 *        `[200, 401, 403, 422]` to validate route mounting — the
 *        endpoint either returns logs, refuses on auth, or rejects the
 *        request shape, all of which prove the route is live.
 *
 *   D3 — Background review "approve" loop is also non-HTTP in the
 *        current implementation. Future tasks may add `/approvals` etc.
 *        when the surface graduates; this file is the stand-in until
 *        those routes land.
 *
 * Real backend is reached via Playwright's built-in `request` fixture
 * (per R6 — no `realBackend` conftest fixture); assumes the conda
 * `sage-backend` env has the FastAPI process up on 127.0.0.1:8765.
 */

import { test, expect } from '@playwright/test';

const BACKEND_URL = process.env.SAGE_BACKEND_URL || 'http://127.0.0.1:8765';

test(
  'evolution live deep: /logs endpoint reachable',
  { tag: '@release' },
  async ({ request }) => {
    // R10: this test is the live analog of the brief's `signal → draft`
    // round-trip, but does not require an LLM key — `/logs` is a
    // read-only endpoint over the evolution event store.
    const r = await request.get(`${BACKEND_URL}/api/v1/evolution/logs`);
    // Acceptable statuses: 200 (logs returned), 401/403 (auth refused —
    // route mounted but needs creds), 422 (request shape rejected). Any
    // of these proves the route is live. 404 would mean it's NOT
    // mounted and is intentionally NOT in the tolerance set.
    expect([200, 401, 403, 422]).toContain(r.status());

    if (r.status() === 200) {
      const body = await r.json();
      expect(Array.isArray(body), 'logs response must be an array').toBe(true);
    }
  },
);
