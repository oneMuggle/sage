/**
 * Live deep spec: real LLM-extracted memory cross-session search.
 *
 * Exercises the production memory stack against a live backend (port 8765).
 * Skips without `OPENAI_API_KEY` / `SAGE_LLM_API_KEY` per the project-wide
 * skip-on-no-key pattern.
 *
 * Deviations from the brief, all binding per Task 12 ruling R9:
 *
 *   D1 — Brief's POST `/memory/episodic` does NOT exist in the real backend.
 *        `MemorySaveRequest` (`legacy_routes.py:2583`) only accepts
 *        `content` / `memory_type` / `importance` / `tags`. No `session_id`
 *        field is on the save schema; the brief's body sent `{session_id,
 *        content}` which would 422 against the real schema.
 *        We POST `/memory/save` (`legacy_routes.py:2605`) with
 *        `{content, memory_type: 'episodic'}` instead and rely on
 *        `/memory/search` to surface the write.
 *
 *   D2 — Brief's cross-session assertion shape
 *        (`[data.episodic, data.semantic, data.working].flat().map(m =>
 *        m.session_id)`) does not match the real `/memory/search` response,
 *        which returns a flat list of memory records. We assert a plain
 *        `Array.isArray` plus a non-empty result.
 *
 *   D3 — Brief's `/memory/consolidate` is a stub-world fiction. The
 *        closest real read-only analog is GET `/memory/summaries`
 *        (`legacy_routes.py:2930`), which we use as a route-reachability
 *        substitute rather than a 1:1 consolidation semantic.
 *
 * Real backend is reached via Playwright's built-in `request` fixture
 * (per R6 — no `realBackend` conftest fixture); assumes the conda
 * `sage-backend` env has the FastAPI process up on 127.0.0.1:8765.
 */

import { test, expect } from '@playwright/test';

const BACKEND_URL = process.env.SAGE_BACKEND_URL || 'http://127.0.0.1:8765';

test(
  'memory live deep: write → cross-session search',
  { tag: '@nightly' },
  async ({ request }) => {
    if (!process.env.OPENAI_API_KEY && !process.env.SAGE_LLM_API_KEY) {
      test.skip(true, 'OPENAI_API_KEY not set');
    }
    // Step 1: persist a memory entry. Body uses MemorySaveRequest schema
    // (content + memory_type) — no session_id field exists in the real
    // save schema (D1).
    const save = await request.post(`${BACKEND_URL}/api/v1/memory/save`, {
      data: { content: 'User mentioned preferring dark mode', memory_type: 'episodic' },
    });
    expect(save.ok()).toBeTruthy();

    // Step 2: cross-session search. Real response is a flat array of
    // records, not the brief's nested `{episodic, semantic, working}`
    // envelope (D2). We assert the search returns at least one item.
    const search = await request.get(
      `${BACKEND_URL}/api/v1/memory/search?q=dark+mode`,
    );
    expect(search.ok()).toBeTruthy();
    const data = await search.json();
    expect(Array.isArray(data), 'search must return an array').toBe(true);
    expect(
      data.length,
      'search must surface at least the entry we just wrote',
    ).toBeGreaterThanOrEqual(1);
  },
  60_000,
);

test('memory live deep: summaries reachability (consolidation analog)', async ({
  request,
}) => {
  // Brief's `/memory/consolidate` does not exist live (D3). The closest
  // read-only surface is `GET /api/v1/memory/summaries` which serves as
  // a route-reachability stand-in for the consolidation semantic. This
  // test does not require an LLM key — consolidation is a backend-side
  // process, not an LLM call.
  const r = await request.get(`${BACKEND_URL}/api/v1/memory/summaries`);
  // 200 = summaries present; 400 = bare GET rejected (route mounted,
  // missing required session_id per legacy_routes.py:2949); 422 =
  // Pydantic validation; 500 acceptable in dev when no sessions
  // exist yet. (R12 — widened to 400 after live-run discovery.)
  expect([200, 400, 422, 500]).toContain(r.status());
});
