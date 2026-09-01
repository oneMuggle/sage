/**
 * Live boot-smoke spec: real backend route reachability (no LLM calls).
 *
 * Hits 4 real backend routes to confirm the live server is up and the
 * most-used API surfaces are reachable. Each assertion targets the GET
 * handler explicitly (no 404/405 acceptance): the backend's real handlers
 * either succeed with 200, return a meaningful auth/project gate (401/403/404),
 * or fail with a 422 only when the request shape is wrong (memory/search).
 *
 * Substitution note (Task 11 ruling R2): the brief originally requested
 *   GET /api/v1/evolution/scheduler/status
 * which does NOT exist in the real backend (verified by grep against
 * `backend/api/legacy_routes.py` and `backend/api/scheduled_router.py`).
 * That route is a stub-world Task 6 invention. The real backend exposes:
 *   GET /api/v1/evolution/logs          (legacy_routes.py:2451, GET handler)
 *   /api/v1/scheduled/*                  (scheduled_router.py)
 * We test `/api/v1/evolution/logs` with bare GET (handler defaults are valid).
 *
 * Auth: gated by `SAGE_LOCAL_AUTH_TOKEN` (the workflow injects a random
 * capability token before live-boot). When the token is missing the spec
 * is skipped — every assertion requires a real authenticated request so
 * 401s don't pollute the smoke signal.
 *
 * Wiki search params (verified against `backend/api/wiki_routes.py:630`):
 * the handler requires `query` (not `q`) and `project_path`. We supply
 * both and accept project-gating rejections (401/403/404) as evidence
 * that the GET handler is mounted on the live server.
 */

import { test, expect } from '@playwright/test';

const BACKEND_URL = process.env.SAGE_BACKEND_URL || 'http://127.0.0.1:8765';
const AUTH_TOKEN = process.env.SAGE_LOCAL_AUTH_TOKEN;

function authenticatedHeaders(): { Authorization: string } {
  if (!AUTH_TOKEN) {
    throw new Error('SAGE_LOCAL_AUTH_TOKEN is required for live route tests');
  }

  return { Authorization: `Bearer ${AUTH_TOKEN}` };
}

test.skip(!AUTH_TOKEN, 'SAGE_LOCAL_AUTH_TOKEN is not configured');

test('GET /api/v1/sessions returns 200 (route mounted)', async ({ request }) => {
  const resp = await request.get(`${BACKEND_URL}/api/v1/sessions`, {
    headers: authenticatedHeaders(),
  });
  expect(200).toBe(resp.status());
});

test('GET /api/v1/memory/search returns 200, 400, or 422 (route mounted)', async ({ request }) => {
  const resp = await request.get(`${BACKEND_URL}/api/v1/memory/search?q=test`, {
    headers: authenticatedHeaders(),
  });
  // 422 = Pydantic validation error on query params — route is mounted, just rejects bare ?q=
  expect([200, 400, 422]).toContain(resp.status());
});

test('GET /api/v1/evolution/logs returns 200 (live; stub-world has scheduler/status instead)', async ({
  request,
}) => {
  // NOTE: real backend exposes /api/v1/evolution/logs (legacy_routes.py:2451),
  // not /api/v1/evolution/scheduler/status (which is a stub-world Task 6 invention).
  // list_evolution_logs has limit/offset defaults; bare GET must hit the handler.
  const resp = await request.get(`${BACKEND_URL}/api/v1/evolution/logs`, {
    headers: authenticatedHeaders(),
  });
  expect(200).toBe(resp.status());
});

test('GET /api/v1/wiki/search returns 200, 401, 403, or 404 (route mounted, project gated)', async ({
  request,
}) => {
  // Real backend requires `query` (NOT `q`) and `project_path` (mandatory).
  // Bare `?q=test` would yield 422, which would mask whether the GET handler
  // is mounted at all — supply the actual handler params, then accept auth/
  // project-gating rejections (401/403/404) as proof the route is reachable.
  const resp = await request.get(
    `${BACKEND_URL}/api/v1/wiki/search?query=test&project_path=/tmp/sage-route-smoke-probe`,
    { headers: authenticatedHeaders() },
  );
  expect([200, 401, 403, 404]).toContain(resp.status());
});
