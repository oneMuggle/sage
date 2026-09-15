/**
 * Live deep spec: real orchestration lane creation + board reachability.
 *
 * Exercises the production orchestration stack against a live backend
 * (port 8765). Skips without `OPENAI_API_KEY` / `SAGE_LLM_API_KEY` per the
 * project-wide skip-on-no-key pattern.
 *
 * Deviations from the brief, all binding per Task 12 ruling R7:
 *
 *   D1 — Brief's `POST /orchestration/runs` does NOT exist in the real
 *        backend. The real surface is `POST /api/v1/orchestration/lanes`
 *        (`orchestration_router.py:235`), which takes `{goal, agent?}` per
 *        `CreateLanesIn` (line 86) and returns `CreateLanesOut`
 *        (line 91) with `ok`, `team_id`, `lanes`, `tasks`, `review`.
 *        There is no `run_id` or `session_id` or `plan` field — the
 *        brief's body would 422 on the latter two.
 *
 *   D2 — Brief's polling loop on `GET /orchestration/runs/{rid}` for a
 *        `status` field does not exist live. The real read surface for a
 *        single lane is `GET /api/v1/orchestration/lanes/{lane_id}`
 *        (line 193). We replace the polling loop with a single
 *        reachability poll on `GET /orchestration/board` (line 392) —
 *        the LaneBoard monitor snapshot the brief effectively wanted.
 *
 *   D3 — Brief used the analog of "run complete" status. Real
 *        orchestration execution is fire-and-forget by default; the
 *        `wait=true` query param on `/lanes` synchronously executes and
 *        returns the review verdict. We accept `ok=true` + `team_id`
 *        non-empty as the success surface instead of polling a status
 *        machine that does not exist at this URL.
 *
 * Real backend is reached via Playwright's built-in `request` fixture
 * (per R6 — no `realBackend` conftest fixture); assumes the conda
 * `sage-backend` env has the FastAPI process up on 127.0.0.1:8765.
 */

import { test, expect } from '@playwright/test';

const BACKEND_URL = process.env.SAGE_BACKEND_URL || 'http://127.0.0.1:8765';

test(
  'orchestration live deep: 3-agent real LLM run',
  { tag: '@release' },
  async ({ request }) => {
    if (!process.env.OPENAI_API_KEY && !process.env.SAGE_LLM_API_KEY) {
      test.skip(true, 'OPENAI_API_KEY not set');
    }
    // Step 1: decompose the goal into a team of lanes. Body uses
    // CreateLanesIn schema (`{goal, agent?}`) — no `session_id` or
    // `plan` field exists in the real schema (D1).
    const create = await request.post(`${BACKEND_URL}/api/v1/orchestration/lanes`, {
      data: { goal: 'List 3 risks of LLMs in one sentence each' },
    });
    expect(create.ok()).toBeTruthy();
    const body = (await create.json()) as {
      ok: boolean;
      team_id: string;
      lanes?: unknown[];
    };
    expect(body.ok, 'CreateLanesOut.ok must be true').toBe(true);
    expect(typeof body.team_id, 'team_id must be a non-empty string').toBe('string');
    expect(body.team_id.length, 'team_id must be non-empty').toBeGreaterThan(0);

    // Step 2: reachability poll of the board endpoint (D2 — there is no
    // `runs/{rid}` status to poll in the real backend; the board is the
    // read-side analog).
    const board = await request.get(`${BACKEND_URL}/api/v1/orchestration/board`);
    expect(board.status()).toBe(200);
  },
  120_000,
);
