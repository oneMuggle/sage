/**
 * Live deep spec: real LLM chat stream round-trip.
 *
 * Exercises the production chat-stream handshake against a live backend
 * (port 8765). Skips without `OPENAI_API_KEY` / `SAGE_LLM_API_KEY` per the
 * project-wide skip-on-no-key pattern.
 *
 * Three deviations from the brief, all binding per Task 12 rulings R1 + R11:
 *   R1a — Response field name: real backend serializes `streamId`
 *         (camelCase) per `backend/api/legacy_routes.py:1644` docstring.
 *         Brief used `stream_id`.
 *   R1b — Request body field: `ChatRequest` requires `message: str`
 *         (`legacy_routes.py:151`). Brief used `content` — that 422s.
 *   R11 — Body field corrected to `message`, response destructure to
 *         `streamId`; otherwise this test would skip (no LLM key) and
 *         never actually exercise the schema corrections.
 *
 * Real backend is reached via Playwright's built-in `request` fixture
 * (per R6 — no `realBackend` conftest fixture); assumes the conda
 * `sage-backend` env has the FastAPI process up on 127.0.0.1:8765.
 */

import { test, expect } from '@playwright/test';

const BACKEND_URL = process.env.SAGE_BACKEND_URL || 'http://127.0.0.1:8765';

test(
  'chat live deep: real LLM responds coherently',
  { tag: '@nightly' },
  async ({ request }) => {
    if (!process.env.OPENAI_API_KEY && !process.env.SAGE_LLM_API_KEY) {
      test.skip(true, 'OPENAI_API_KEY not set');
    }
    // Step 1: open the stream. R1b — body uses `message`, not `content`.
    const create = await request.post(`${BACKEND_URL}/api/v1/chat/stream`, {
      data: { session_id: 'sess_live_chat', message: 'What is 2+2? Answer in one word.' },
    });
    expect(create.ok()).toBeTruthy();
    // R1a — response field is `streamId` (camelCase), not `stream_id`.
    const { streamId } = await create.json();
    expect(typeof streamId, 'streamId must be a string uuid').toBe('string');
    expect(streamId.length, 'streamId must be non-empty').toBeGreaterThan(0);

    // Step 2: attach to the NDJSON event feed; the LLM should have
    // produced at least one chunk mentioning "four" or "4".
    const resp = await request.get(`${BACKEND_URL}/api/v1/chat/stream/${streamId}`);
    expect(resp.status()).toBe(200);
    const body = await resp.text();
    expect(body).toMatch(/four|4/);
  },
  60_000,
);
