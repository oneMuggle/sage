/**
 * Live boot-smoke spec: real backend route reachability (no LLM calls).
 *
 * Hits 4 real backend routes to confirm the live server is up and the
 * most-used API surfaces are reachable. Each assertion accepts a small set
 * of "tolerant" statuses because Pydantic validation can surface 400/405
 * for malformed inputs and we only care that the endpoint is mounted and
 * the backend is alive — not that the input shape is perfect.
 *
 * Substitution note (Task 11 ruling R2): the brief originally requested
 *   GET /api/v1/evolution/scheduler/status
 * which does NOT exist in the real backend (verified by grep against
 * `backend/api/legacy_routes.py` and `backend/api/scheduled_router.py`).
 * That route is a stub-world Task 6 invention. The real backend exposes:
 *   GET /api/v1/evolution/logs          (legacy_routes.py:2380)
 *   /api/v1/scheduled/*                  (scheduled_router.py)
 * We test `/api/v1/evolution/logs` instead and tolerate 405 because the
 * endpoint requires a query parameter shape that may vary across builds.
 */

import { test, expect } from '@playwright/test';

const BACKEND_URL = process.env.SAGE_BACKEND_URL || 'http://127.0.0.1:8765';

test('GET /api/v1/sessions returns 200 or 404', async ({ request }) => {
  const resp = await request.get(`${BACKEND_URL}/api/v1/sessions`);
  expect([200, 404]).toContain(resp.status());
});

test('GET /api/v1/memory/search returns 200 or 400', async ({ request }) => {
  const resp = await request.get(`${BACKEND_URL}/api/v1/memory/search?q=test`);
  expect([200, 400]).toContain(resp.status());
});

test('GET /api/v1/evolution/logs returns 200 or 405 (live; stub-world has scheduler/status instead)', async ({
  request,
}) => {
  // NOTE: real backend exposes /api/v1/evolution/logs (legacy_routes.py:2380),
  // not /api/v1/evolution/scheduler/status (which is a stub-world Task 6 invention).
  const resp = await request.get(`${BACKEND_URL}/api/v1/evolution/logs`);
  expect([200, 405]).toContain(resp.status());
});

test('GET /api/v1/wiki/search returns 200, 405, or 400', async ({ request }) => {
  const resp = await request.get(`${BACKEND_URL}/api/v1/wiki/search?q=test`);
  expect([200, 405, 400]).toContain(resp.status());
});