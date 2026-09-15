/**
 * Live boot-smoke spec: real backend /health endpoint reachability.
 *
 * This spec assumes the FastAPI backend is already running on port 8765
 * (started externally via the conda `sage-backend` environment). It does
 * NOT spawn the backend — that lifecycle is owned by Task 7's
 * `_real_backend.RealBackend` class and future boot-smoke orchestration
 * (Task 13 will wire `--project=electron-live-boot`). This file intentionally
 * uses Playwright's built-in `request` fixture to match the brief's pattern:
 * small, declarative, and decoupled from Python subprocess management.
 *
 * Acceptance: status 200 and JSON body `{ status: "ok" }`.
 */

import { test, expect } from '@playwright/test';

const BACKEND_URL = process.env.SAGE_BACKEND_URL || 'http://127.0.0.1:8765';

test('real backend GET /health returns 200 with status=ok', async ({ request }) => {
  const resp = await request.get(`${BACKEND_URL}/health`);
  expect(resp.status()).toBe(200);
  const body = await resp.json();
  expect(body.status).toBe('ok');
});