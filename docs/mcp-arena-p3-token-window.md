# Arena Port P3 — Token Window (hidden Electron minter)

Date: 2026-09-19
Status: CLOSED (code + tests + smoke green; live in-app run pending P5 UI)
Plan ref: `docs/mcp-aren-card-port-plan.md` §5.9 / §5.10

## Goal

A hidden Electron window keeps a fresh reCAPTCHA V3 token in the backend cache so the
P4 draw engine never waits on minting in the draw path. Push model (not the reference's
pull model): the window polls `GET /api/v1/arena/token-window/state`; the backend raises
`needed` when a draw thread blocks (condition variable) or on warmup; the window mints
in-page (`grecaptcha.enterprise.execute`, action `agentic_chat_submit`) and POSTs the
token. Reference semantics preserved: ready-is-only-a-hint (retry after reload), token
age gate ~110 s (V3 lives ~2 min), proxy switches only via backend-mapped local relay
(Chromium never sees credentials).

## What landed

Backend:

- `backend/services/arena_token_cache.py` — `TokenWindowCache`: thread-safe push/get with
  condition-variable wake; `get(max_age_sec, wait_sec)` raises `needed` while waiting;
  `push` validates shape (50 < len < 20000 → 400 otherwise), stores `{token, exit_ip,
  ua}`; `mark_rejected` counts create_chat reCAPTCHA denials (P4 熔断 input);
  `request_proxy_change` maps upstream → `arena_proxy_relay.local_proxy` before the
  window ever sees a proxy URL. Module singleton `get_token_window_cache(config)`.
  `token_window.use_proxy` (blocking acquire) is consumed by the P4 draw engine; P3
  ships the mechanism with the window running direct.
- `backend/api/arena_routes.py` — `POST /token-window/push` (gated: master+sub switch,
  403; bad shape 400), `GET /token-window/state` (never 403 — the window must be able
  to read `enabled=false` to stop gracefully), `GET /token-window/health` (diagnostics
  for the UI card). `/capabilities` now reports `token_window.available` (sub-flag
  gated) + `ready` (cache health). Added the `shutdown_arena_services` alias —
  main.py:712's lifespan hook calls the plural name while #1211's merge renamed the
  routes export to the singular; the alias keeps both true.
- `backend/config/arena_automation.py` — `TokenWindowConfig.poll_interval_sec`
  (default 2.0, 0.5–60) so the window's poll cadence is config-driven; yaml comment
  block documents the sub-section.

Electron:

- `electron/arenaTokenWindow.ts` — `ArenaTokenWindowController`: partition
  `persist:arena-token`, `show:false`, `backgroundThrottling:false` (anti-throttle,
  acceptance A5), poll loop with dynamic interval from `state.poll_interval_sec`
  (clamped 0.5–60 s), `needed` → mint (reload-once retry, ready-is-only-a-hint),
  `want_proxy`/`proxy_url` → `session.setProxy` exactly once per change, `enabled=false`
  or push 401/403 → destroy window and stop; push backoff 1 s → 30 s exponential;
  `before-quit` cleanup. `registerArenaTokenWindow()` wires IPC
  `sage:arena-token:status|start|stop|reload|pick-proxy` (pick-proxy rejects
  credentialed URLs — those must go through the backend relay flow).
- `electron/main.ts` / `electron/preload.ts` / `src/shared/types/electron-api.d.ts` —
  controller registration at app startup, preload bridge, typed renderer API.

Tests:

- `backend/tests/unit/services/test_arena_token_cache.py` — 12 cases: push shape/refresh
  age, get wait/wake + needed lifecycle, stale rejection, reject counting, relay mapping
  (credentials never reach `state.proxy_url`), singleton rebuild, route contracts
  (403 gating for push, state/health never 403 even uninitialized, poll interval from
  config).
- `electron/__tests__/arenaTokenWindow.test.ts` — 9 cases over injected seams
  (fake window/fetch/delay/clock): warmup push with Bearer auth + exit_ip/ua round
  trip, needed-triggered mint, enabled=false destroys, 502 backoff then success, 403
  stops, mint-failure reload-once retry, pick-proxy rules, want_proxy single-apply,
  IPC channel wiring + before-quit.

## Verification

- Sandbox `verify_p3/` tree (current remote modules + stubs): **84/84** (the one
  browser-dependent assertion verified via patched `_browser_available`).
- Remote `pytest -k "arena or temporary_mail"`: **242 passed / 1 skipped**.
- Remote `npx tsc -p tsconfig.electron.json --noEmit`: clean.
- Remote `npx vitest run electron/__tests__/arenaTokenWindow.test.ts`: **9/9**.
- Smoke (`.tmp-arena-p3/smoke_p3.py` + `p3_harness.cjs`): in-process uvicorn +
  LocalAuthMiddleware + arena router; node harness driving the compiled controller with
  a fake window; report at `.tmp-arena-p3/smoke_report.json`:

  | acceptance | result |
  |---|---|
  | A1 health.ready + exit_ip == window-reported IP | PASS (ready, exit_ip 203.0.113.7) |
  | A2 20 consecutive on-demand rounds, 0 failures | PASS (0/20 fails) |
  | A4 needed → push < 3 s each round | PASS (first needed reaction 1.391 s; steady-state mint rounds 0.406–0.437 s; the 0.0 s rounds are by-design fresh-token reuse inside max_age) |
  | A3 backend restart (30 s down) → reconnect ≤ 60 s | PASS (3.219 s; harness log shows the poll backoff ladder 1→2→4→8→16 s during the outage, then a push through the restarted server) |
  | A5 300 s idle → wakes ≤ 30 s | PASS (0.406 s) |

  Smoke config: `max_age_sec=0.5`, `poll_interval_sec=0.5` (forcing every third
  round through the real needed→mint→push chain), fake window with realistic
  token length (2489 chars), local-auth Bearer on every call. Final state:
  backend health ready/count=9, harness alive 342 s, exit_ip consistent on both
  sides. Report kept at `.tmp-arena-p3/smoke_report.json` + `harness_stdout.log`.

  One interface note surfaced by the smoke: `cache.get()` serves the same token
  while it is fresh (correct for diagnostics/warm reads). The P4 draw engine
  must decide consume-on-draw semantics (V3 tokens are single-use per
  create_chat) — either a `consume=True` flag or invalidate-after-read; the
  needed/pre-mint machinery already supports it (a consumed token makes the
  next `get` raise `needed` and the window pre-mints).
