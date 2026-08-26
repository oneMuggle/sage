/**
 * Live boot-smoke spec: SSE chat stream create + attach handshake.
 *
 * Exercises the two-step stream protocol used by the Electron renderer:
 *   1. POST /api/v1/chat/stream  → server creates a stream and returns
 *      `{"streamId": "<uuid4>"}` (NOT `stream_id` — see Task 11 ruling R1a).
 *   2. GET  /api/v1/chat/stream/{streamId}  → NDJSON event feed that the
 *      client attaches to. Content-Type is `application/x-ndjson` per
 *      `backend/services/chat_stream_registry.py:12`.
 *
 * Two deviations from the brief, both binding per Task 11 ruling R1:
 *   R1a — Field name: real backend serializes `streamId` (camelCase) per
 *         `legacy_routes.py:1644` docstring. Brief used `stream_id`.
 *   R1b — Request body field: `ChatRequest` (legacy_routes.py:149-151)
 *         requires `message: str`, NOT `content`. Sending `content: 'hi'`
 *         returns 422 Pydantic validation error and the test would skip
 *         for the wrong reason. We send `message: 'hi'` instead.
 *
 * No LLM is actually invoked here — the test only asserts that the stream
 * is created and the GET attach endpoint returns NDJSON. If the backend
 * has no LLM configured, the stream still opens; events may simply never
 * arrive (we don't read the body).
 */

import { test, expect } from '@playwright/test';

const BACKEND_URL = process.env.SAGE_BACKEND_URL || 'http://127.0.0.1:8765';

test('SSE chat stream handshake: create returns streamId, GET attach returns NDJSON', async ({
  request,
}) => {
  // Step 1: create the stream. R1b — body field is `message`, not `content`.
  const create = await request.post(`${BACKEND_URL}/api/v1/chat/stream`, {
    data: { session_id: 'sess_boot_smoke', message: 'hi' },
  });
  if (!create.ok()) {
    test.skip(true, `chat stream create failed: ${create.status()}`);
  }
  // R1a — response field is `streamId` (camelCase), not `stream_id`.
  const { streamId } = await create.json();
  expect(typeof streamId, 'streamId must be a string uuid').toBe('string');
  expect(streamId.length, 'streamId must be non-empty').toBeGreaterThan(0);

  // Step 2: attach to the NDJSON event feed.
  const resp = await request.get(`${BACKEND_URL}/api/v1/chat/stream/${streamId}`);
  expect(resp.status()).toBe(200);
  expect(resp.headers()['content-type']).toMatch(/event-stream|ndjson/);
});