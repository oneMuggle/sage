/**
 * Live boot-smoke spec: real backend route reachability (no LLM calls).
 *
 * Hits 4 real backend routes to confirm the live server is up and the
 * most-used API surfaces are reachable. Each assertion targets the GET
 * handler explicitly (no 404/405 acceptance): the backend's real handlers
 * either succeed with 200, or return the expected project gate (403) for the
 * deliberately unregistered wiki probe path. The memory/search assertion also
 * permits the documented validation responses.
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
 * capability token before live-boot). A missing token must fail at request
 * execution time so every route test reports the misconfiguration.
 *
 * Wiki search params (verified against `backend/api/wiki_routes.py:630`):
 * the handler requires `query` (not `q`) and `project_path`. We supply both
 * and use an unregistered absolute path whose authenticated response is 403.
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

test('GET /api/v1/wiki/search rejects an unregistered project with 403', async ({ request }) => {
  // Real backend requires `query` (NOT `q`) and `project_path` (mandatory).
  // Use the actual handler params and an unregistered absolute path. With a
  // valid token, authorize_registered_project deterministically returns 403;
  // 401 means authentication failed and 404 means the route is not mounted.
  const resp = await request.get(
    `${BACKEND_URL}/api/v1/wiki/search?query=test&project_path=/tmp/sage-route-smoke-probe`,
    { headers: authenticatedHeaders() },
  );
  expect(403).toBe(resp.status());
});
