---
title: Arena Automation & Model Probe Design
status: draft
created: 2026-09-16
owner: sage-core
scope: cross-platform
---

# Arena Automation & Model Probe — Design Spec

> **Summary:** Integrate Arena account automation (registration, login, message dispatch) with real-time model identity detection via CDP traffic observation. Both main and release/win7 branches; feature-flagged off by default; Win7 strictly Chromium 106.

---

## 1. Background & Goals

### 1.1 Problem

Arena.ai routes conversations through opaque gateway endpoints that mask upstream model names. Users need to:

1. Manage multiple Arena accounts for parallel evaluation workloads
2. Know which actual model (e.g. `gpt-6-astra-high`, `claude-opus-4-6`) is responding — not just the gateway alias (`model-a`, `model-b`)
3. Automate the repetitive parts (login, message dispatch) without risking account bans or violating site ToS around CAPTCHA/MFA

### 1.2 Source Projects

| Project | Tech | What to port | What to skip |
|---|---|---|---|
| `ArenaHelper` | C# WinForms/WebView2 | Auth flow logic, account pool model, attachment handling | WinForms UI, DPAPI storage (Windows-only), WebView2 specifics |
| `arena-model-probe` | Node.js ESM + Python | Evidence classification, UUID→model mapping, run trace resolution, protocol fingerprinting | Tampermonkey injection layer, CDP driver (use Sage's `browser_cdp.py`) |

### 1.3 Goals

- [ ] G1: Auto-register accounts on arena.ai (email + password + verification code)
- [ ] G2: Auto-fill credentials and dispatch messages (with Thinking filter)
- [ ] G3: Detect actual model names in real-time via CDP traffic observation
- [ ] G4: Account pool with configurable limits, cross-restart persistence
- [ ] G5: Win7 parity — feature-flagged, Chromium 106 compatible

### 1.4 Non-Goals (Security Boundaries)

- ❌ **No CAPTCHA/MFA auto-bypass** — these require human intervention; the system pauses and waits
- ❌ **No unauthorized account creation** — only accounts explicitly added by the user/org are managed
- ❌ **No traffic interception outside Sage-managed browser sessions** — pure passive observation of tabs Sage itself opened
- ❌ **No credential exfiltration** — all stored credentials encrypted at rest, never logged in plaintext

---

## 2. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│  Electron UI                                                         │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │  ArenaTaskPanel (model probe results, account status)        │  │
│  │  AccountManager (pool CRUD, health indicators)               │  │
│  │  SettingsCard (feature flag, quota config)                   │  │
│  └──────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
                                    │ IPC
┌─────────────────────────────────────────────────────────────────────┐
│  FastAPI Backend                                                      │
│                                                                        │
│  ┌─────────────────────────────────────────────────────────────────┐│
│  │  Arena Automation Layer                                           ││
│  │                                                                   ││
│  │  ┌─────────────────────┐  ┌──────────────────────────────────┐ ││
│  │  │  ArenaAccountService │  │  ArenaAdapter                     │ ││
│  │  │  • pool mgmt (SQLite)│  │  • login/register flow           │ ││
│  │  │  • credential vault  │  │  • message dispatch              │ ││
│  │  │  • health tracking   │  │  • Thinking filter               │ ││
│  │  └─────────────────────┘  │  • attachment upload               │ ││
│  │                            └──────────────────────────────────┘ ││
│  │                                                                   ││
│  │  ┌─────────────────────────────────────────────────────────────┐││
│  │  │  TemporaryMailProvider (abstract)                            │││
│  │  │  ├── MailTMAdapter                                           │││
│  │  │  ├── GuerrillaMailAdapter                                    │││
│  │  │  └── [user-supplied adapters]                                │││
│  │  └─────────────────────────────────────────────────────────────┘││
│  └─────────────────────────────────────────────────────────────────┘│
│                                                                        │
│  ┌─────────────────────────────────────────────────────────────────┐│
│  │  Model Probe Layer                                                ││
│  │                                                                   ││
│  │  ┌──────────────────────────┐  ┌─────────────────────────────┐ ││
│  │  │  ModelObservationService │  │  ModelIdentityResolver        │ ││
│  │  │  • persistent CDP obs.   │  │  • evidence aggregation       │ ││
│  │  │  • Node.js worker bridge │  │  • UUID→model mapping         │ ││
│  │  │  • event stream to UI    │  │  • run trace resolution       │ ││
│  │  └──────────────────────────┘  └─────────────────────────────┘ ││
│  └─────────────────────────────────────────────────────────────────┘│
│                                                                        │
│  ┌─────────────────────────────────────────────────────────────────┐│
│  │  Shared Infrastructure (existing)                                 ││
│  │  browser_cdp.py • browser_ws.py • orchestration • EventHub        ││
│  └─────────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────────┘
```

---

## 3. Component Design

### 3.1 Feature Flag & Configuration

**Module:** `backend/config/arena_automation.py`

```python
class ArenaAutomationConfig:
    enabled: bool = False                    # master kill switch
    max_accounts: int = 5                    # pool size limit
    max_concurrent_sessions: int = 2         # global concurrency cap
    mail_provider: str = "mailtm"            # which adapter to use
    mail_api_key: Optional[str] = None       # provider-specific secret
    account_idle_timeout_sec: int = 300      # release reserved accounts after N sec
    probe_evidence_cap: int = 500            # max evidence items per session
    failure_isolation_threshold: int = 3     # N consecutive failures → isolate account
    manual_captcha_timeout_sec: int = 180    # how long to wait for user to solve CAPTCHA
```

Config is loaded from `backend/config/arena_automation.yaml` (user-editable). Feature flag is checked at every entry point; when `enabled=False`, all routes return 403 and no background workers start.

### 3.2 ArenaAccountService — Account Pool Management

**Module:** `backend/services/arena_accounts.py`

**Storage:** SQLite table `arena_accounts` (created only when feature enabled).

```
arena_accounts
├── id (PK, uuid)
├── email (unique, encrypted)
├── password (encrypted)
├── state (available | reserved | degraded | disabled | destroyed)
├── last_used_at (nullable datetime)
├── failure_count (int, reset on success)
├── isolated_at (nullable datetime)
├── created_at, updated_at
└── notes (text, nullable)
```

**Encryption:** Credentials encrypted at rest using `cryptography.fernet.Fernet` with a key derived from `SAGE_LOCAL_AUTH_TOKEN` (already present in the process environment). On Win7, same approach — `cryptography` is available in `requirements-py38.txt`.

**State Machine:**

```
available ──[reserve]──▶ reserved ──[release]──▶ available
     │                        │
     │                   [failure]
     │                        │
     │                        ▼
     │                   degraded ──[threshold]──▶ disabled
     │                        │                       │
     │                   [reset]                      │
     └────────────────────────┘                  [manual re-enable]
                                                      │
                                                      ▼
                                                   destroyed
```

**Account Selection (scheduling):**

- Within an account: serial (one operation at a time per account, enforced by SQLite row-level lock via `SELECT ... FOR UPDATE` pattern using `BEGIN IMMEDIATE`)
- Across accounts: global concurrency cap (`max_concurrent_sessions`); queue waits for a slot
- Selection priority: `available` accounts sorted by `last_used_at ASC` (least-recently-used first, for even wear)

**API:**

```
POST   /api/v1/arena/accounts              — create account
GET    /api/v1/arena/accounts              — list pool
DELETE /api/v1/arena/accounts/:id          — soft-delete (→ disabled)
POST   /api/v1/arena/accounts/:id/isolate  — manual isolate
POST   /api/v1/arena/accounts/:id/enable   — re-enable from disabled
GET    /api/v1/arena/accounts/:id/stats    — usage stats
```

### 3.3 TemporaryMailProvider — Disposable Email Abstraction

**Module:** `backend/services/temporary_mail/`

```
temporary_mail/
├── __init__.py
├── base.py          # TemporaryMailProvider ABC
├── mailtm.py        # Mail.tm REST API adapter
├── guerrilla.py     # Guerrilla Mail adapter
└── registry.py      # provider_name → class mapping
```

**ABC Interface:**

```python
class TemporaryMailProvider(ABC):
    @abstractmethod
    async def create_mailbox(self) -> Mailbox:
        """Returns (email_address, password_or_token)."""

    @abstractmethod
    async def wait_for_code(
        self,
        mailbox: Mailbox,
        subject_pattern: str = r"verification|verify|code",
        timeout_sec: int = 120,
        poll_interval_sec: int = 5,
    ) -> Optional[str]:
        """Poll inbox for a message matching subject_pattern; extract numeric/alphanumeric code."""

    @abstractmethod
    async def destroy_mailbox(self, mailbox: Mailbox) -> None:
        """Cleanup; best-effort, never raises."""
```

**Extensibility:** Users can add custom providers by dropping a Python file into `~/.sage/temp_mail_adapters/` that subclasses `TemporaryMailProvider` and registers itself. The registry auto-discovers these at startup (only when feature flag is on).

### 3.4 ArenaAdapter — Site-Specific Automation

**Module:** `backend/adapters/arena.py`

This is the site-specific logic layer. It takes a `BrowserSession` (from `browser_cdp.py`) and drives Arena.ai pages.

**Key Operations:**

| Operation | CDP Calls | Notes |
|---|---|---|
| `check_login_state()` | `Runtime.evaluate` on `document.querySelector` | Detect logged-in avatar / email in page |
| `fill_login(email, password)` | `DOM.querySelector` + `Input.dispatchKeyEvent` | Type into input fields char-by-char (anti-bot detection) |
| `fill_verification_code(code)` | Same pattern on the OTP input | 6-digit code from temp mail |
| `submit_message(text, thinking_filter)` | Click chat input + type + send button | `thinking_filter`: strip `<thinking>...</thinking>` blocks if user opts out |
| `upload_attachment(path)` | `DOM.setFileInputFiles` | Bypass file chooser dialog |
| `detect_captcha()` | `Runtime.evaluate` checking for hCaptcha/reCAPTCHA iframes | If detected → pause and emit `captcha_required` event |
| `wait_for_response(timeout)` | Observe SSE stream completion via CDP Network domain | Signal when response is fully streamed |

**Thinking Filter:**

Arena responses may include `<thinking>` blocks (internal reasoning). The filter is configurable per-account:

```python
class ThinkingFilter(Enum):
    KEEP = "keep"            # pass through verbatim
    STRIP = "strip"          # remove <thinking>...</thinking> blocks
    SUMMARIZE = "summarize"  # replace with [thinking: N tokens]
```

**CAPTCHA/MFA Handling:**

When `detect_captcha()` finds a CAPTCHA iframe:

1. Emit `arena:captcha-required` event via EventHub with `account_id` and `browser_id`
2. UI shows notification: "CAPTCHA detected — please solve in the Arena browser window"
3. Start a timer (`manual_captcha_timeout_sec`)
4. Poll `detect_captcha()` every 2 seconds; when it returns `False`, resume automation
5. If timeout expires → isolate the account, emit `arena:account-isolated` event

**Error Classification:**

| Error | Action |
|---|---|
| Network timeout | Retry up to 2× with backoff, then mark account `degraded` |
| CAPTCHA timeout | Isolate account (see above) |
| Invalid credentials | Mark account `disabled`, emit alert |
| Rate limit (429) | Back off exponentially, retry up to 3× |
| Site structure change (selector not found) | Emit `arena:adapter-desync` alert, mark account `degraded` |

### 3.5 ModelObservationService — Persistent CDP Observer

**Module:** `backend/services/model_observation.py`

**Problem:** Existing `browser_cdp.py` uses short-lived CDP connections (one per command). Model probing requires a **persistent** WebSocket connection to observe traffic in real-time.

**Solution:** Add a `cdp_persistent_session()` function to `browser_cdp.py` that:

1. Opens a WebSocket to the browser's WS endpoint (same as existing `browser_ws.py`)
2. Keeps the connection alive for the lifetime of the observation
3. Subscribes to `Network.webSocketFrameReceived`, `Network.responseReceived`, `Network.requestWillBeSent`
4. Routes incoming frames to a Python-side event queue
5. Exposes a `subscribe()` interface for consumers

**Node.js Worker Bridge:**

The core model classification logic (`classify.js`, `idmap.js`, `registry.js`) is JavaScript. Rather than porting 2000+ lines of JS to Python, we run a lightweight Node.js worker:

```
backend/
└── services/
    └── model_probe_worker/
        ├── package.json       # zero npm deps
        ├── worker.mjs         # stdin/stdout JSON protocol
        ├── src/
        │   ├── classify.js    # ← symlink from arena-model-probe/src/classify.js
        │   ├── idmap.js       # ← symlink from arena-model-probe/src/idmap.js
        │   ├── registry.js    # ← symlink from arena-model-probe/src/registry.js
        │   ├── learned.js     # ← symlink
        │   └── runmodel.js    # ← symlink
        └── tests/
```

The Python side communicates via subprocess stdin/stdout:

```python
class ModelProbeWorker:
    def __init__(self):
        self.proc = subprocess.Popen(
            ["node", "worker.mjs"],
            cwd=WORKER_DIR,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
        )

    async def push_evidence(self, evidence: dict) -> dict:
        """Send evidence to worker, receive verdict."""
        msg = json.dumps({"cmd": "evidence", "data": evidence})
        self.proc.stdin.write((msg + "\n").encode())
        self.proc.stdin.flush()
        response = self.proc.stdout.readline()
        return json.loads(response)
```

**Win7 Constraint:** Node.js is NOT available on Win7 by default. For Win7, we port the core classification logic to Python:

```python
# backend/services/model_probe_py/classify.py
# Pure Python port of classify.js — evidence aggregation and verdict computation.
# This is ~200 lines, focused on collectModelFields() + resolveEvidence() + verdict logic.
# Does NOT include the full probe — only the evidence→verdict pipeline.
```

The Python port covers:
- `collectModelFields()` — deep JSON traversal for model identifiers
- `scanTextForModel()` — regex fallback
- `resolveEvidence()` — weight aggregation, verdict computation
- `SOURCE_WEIGHTS` — the full weight table
- `MODEL_PATTERNS`, `FAMILY_PROTOCOLS`, `HOST_VENDOR` from registry

The Node.js worker is used only on main branch when Node is available; Win7 always uses the Python port. A `probe_backend` config key selects which to use (`"node"` or `"python"`), defaulting to `"python"` on Win7.

**Evidence Flow:**

```
CDP Network events
       │
       ▼
Python event parser (in persistent CDP session)
       │  extract URL, headers, request body, response body
       │
       ▼
Evidence dict → ModelProbeWorker (Node or Python)
       │
       ▼
Verdict: { modelId, family, confidence, source, evidence_summary }
       │
       ▼
EventHub → ArenaTaskPanel UI
```

**ModelIdentityResolver:**

The resolver enriches raw model strings:

1. **UUID mapping:** Arena often returns UUIDs instead of model names. `idmap.js` (or its Python port) maintains a mapping table fetched from Arena's leaderboard RSC payload. This is refreshed periodically (every 30 min).

2. **Run trace resolution:** When a `public-access-token` appears in the SSE stream, the resolver:
   - Extracts the run ID
   - Calls Arena's internal API `/api/runs/{runId}/trace` (or polls `startAutoResolve` pattern)
   - Extracts `ai.streamText.doStream` span's model label
   - This is the highest-weight evidence (`run.trace.model`, weight 1.00)

3. **Protocol fingerprinting:** When no explicit model string is found, the resolver falls back to protocol framing analysis (Anthropic vs OpenAI vs Google message formats).

### 3.6 ArenaTaskPanel — UI Surface

**Location:** `src/components/ArenaTaskPanel.tsx`

This is the ONLY place where model probe results appear. No global model indicator — the probe is scoped to Arena automation tasks.

**Layout:**

```
┌─────────────────────────────────────────────────────────┐
│  Arena Automation                                   [⚙] │
├─────────────────────────────────────────────────────────┤
│  Account Pool: 3/5 available  1 degraded  1 disabled    │
│  ┌─────────────────────────────────────────────────┐   │
│  │ kai-01    available   last used 2m ago     [···] │   │
│  │ kai-02    reserved    active now          [stop] │   │
│  │ kai-03    degraded    3 failures          [reset]│   │
│  └─────────────────────────────────────────────────┘   │
├─────────────────────────────────────────────────────────┤
│  Active Sessions                                         │
│  ┌─────────────────────────────────────────────────┐   │
│  │ kai-02  chat-abc123                              │   │
│  │ Model: claude-opus-4-6 (confidence: 0.95)        │   │
│  │ Source: run.trace.model                          │   │
│  │ Evidence: [request.body.model, sse.chunk.model]  │   │
│  │ Thinking: 2,340 tokens                           │   │
│  └─────────────────────────────────────────────────┘   │
├─────────────────────────────────────────────────────────┤
│  Recent Verdicts (last 10)                               │
│  ...                                                     │
└─────────────────────────────────────────────────────────┘
```

**IPC Events:**

| Event | Direction | Payload |
|---|---|---|
| `arena:probe-verdict` | Backend → Frontend | `{accountId, sessionId, modelId, family, confidence, source}` |
| `arena:captcha-required` | Backend → Frontend | `{accountId, browserId, timeoutAt}` |
| `arena:account-state-change` | Backend → Frontend | `{accountId, oldState, newState, reason}` |
| `arena:session-started` | Backend → Frontend | `{accountId, sessionId, url}` |
| `arena:session-completed` | Backend → Frontend | `{accountId, sessionId, durationSec, verdicts: [...]}` |

---

## 4. Data Flow — End-to-End Scenario

### 4.1 Account Registration Flow

```
User clicks "Add Account" in AccountManager
       │
       ▼
Backend: POST /api/v1/arena/accounts (provision)
       │
       ▼
ArenaAccountService:
  1. TemporaryMailProvider.create_mailbox() → (email, token)
  2. Launch browser session (browser_cdp.launch_browser)
  3. ArenaAdapter.navigate("https://arena.ai/signup")
  4. ArenaAdapter.fill_signup(email, password, ...)
  5. Check for CAPTCHA → if found, emit arena:captcha-required, wait
  6. TemporaryMailProvider.wait_for_code(mailbox) → verification code
  7. ArenaAdapter.fill_verification_code(code)
  8. ArenaAdapter.submit_signup()
  9. Check for success (redirect to /agent)
  10. Store credentials → arena_accounts table (encrypted)
  11. Set state = available
       │
       ▼
UI: account appears in pool as "available"
```

### 4.2 Message Dispatch + Model Probe Flow

```
User clicks "Send" in ArenaTaskPanel with message text
       │
       ▼
Backend: POST /api/v1/arena/sessions/:id/dispatch
       │
       ▼
ArenaAccountService:
  1. Reserve account (state → reserved)
  2. Ensure browser session is active (launch or reuse)
  3. ArenaAdapter.navigate("https://arena.ai/agent")
  4. ArenaAdapter.check_login_state() → if not logged in, run login flow
  5. Start ModelObservationService on this browser session
       │
       ▼
ModelObservationService:
  1. Open persistent CDP WebSocket to browser
  2. Enable Network domain (Network.enable)
  3. Subscribe to Network.requestWillBeSent, Network.responseReceived,
     Network.webSocketFrameReceived, Network.loadingFinished
  4. For each event → parse → push evidence to ModelProbeWorker
  5. Worker returns verdict → emit arena:probe-verdict via EventHub
       │
       ▼
ArenaAdapter.submit_message(text, thinking_filter=STRIP):
  1. Click chat input
  2. Type message (char-by-char dispatch)
  3. Click send button
  4. wait_for_response(timeout=60) → observe SSE completion via CDP
       │
       ▼
ModelObservationService (running concurrently):
  - First SSE chunk arrives → first verdict within ~800ms
  - Stream continues → verdicts refined with each chunk
  - Stream ends → final verdict with full confidence
       │
       ▼
UI: ArenaTaskPanel updates in real-time:
  "Model: claude-opus-4-6 (confidence: 0.95, source: run.trace.model)"
```

---

## 5. Win7 Constraints

| Aspect | Main | release/win7 |
|---|---|---|
| Python | 3.10 | 3.8 (sage-backend-py38) |
| Pydantic | 2.x | 1.x (compat shim) |
| Chromium | Latest bundled with Electron | 106 (hard cap) |
| CDP features | All stable | Only those available in Chromium 106 |
| Node.js probe worker | Yes (zero deps) | No — Python port only |
| Feature flag | `arena_automation.enabled` | Same flag, same default (off) |
| Encryption | `cryptography.fernet` | Same lib (available in py38) |

**CDP Compatibility:** Chromium 106 supports all the CDP domains we need:
- `Network.enable` / `Network.requestWillBeSent` / `Network.responseReceived` — ✅ since Chrome 60+
- `Network.webSocketFrameReceived` — ✅ since Chrome 60+
- `Runtime.evaluate` — ✅ always
- `DOM.setFileInputFiles` — ✅ since Chrome 60+
- `Input.dispatchKeyEvent` — ✅ always

No cutting-edge CDP features required. The persistent WebSocket connection pattern works identically on Chromium 106.

**Pydantic v1 Compatibility:**

All Pydantic models use v1-compatible syntax:
- `class Config:` instead of `model_config`
- `Field(...)` without v2-only parameters
- No `@model_validator` (use `@validator` instead)
- No `TypeAdapter` (use `parse_obj_as` instead)

---

## 6. Failure Handling & Resilience

### 6.1 Account Isolation

When an account hits `failure_isolation_threshold` (default 3) consecutive failures:

1. Account state → `disabled`
2. All active sessions for this account are cancelled
3. `arena:account-state-change` event emitted with reason
4. UI shows: "Account kai-03 has been isolated after 3 consecutive failures. Manual reset required."
5. User can re-enable via `POST /api/v1/arena/accounts/:id/enable` (resets failure count)

### 6.2 Failure Taxonomy

| Failure | Severity | Auto-Recovery |
|---|---|---|
| Network timeout | Low | Retry 2× with backoff |
| Site structure change (selector not found) | High | Mark `degraded`, emit alert |
| CAPTCHA timeout | Medium | Isolate account |
| Invalid credentials | High | Disable account |
| Rate limit (429) | Medium | Exponential backoff, 3× retry |
| Browser crash | Low | Restart browser, retry once |
| Probe worker crash | Medium | Restart worker, continue without probe |

### 6.3 Graceful Degradation

- If the probe worker fails, automation continues without model detection (verdicts show "unknown")
- If the temp mail provider is down, registration pauses but existing accounts still work
- If CDP persistent connection drops, model observation stops but message dispatch continues

---

## 7. Security Considerations

### 7.1 Credential Storage

- Passwords encrypted with Fernet key derived from `SAGE_LOCAL_AUTH_TOKEN`
- Key derivation: `PBKDF2HMAC(SHA256, salt=machine_id, iterations=480000)` → 32-byte key
- `machine_id` = hash of hostname + username + machine GUID (Linux: `/etc/machine-id`, Windows: registry `MachineGuid`)
- Encryption happens in-memory before DB write; decrypted only when needed for login

### 7.2 Evidence Redaction

The probe worker must never log or expose:
- Raw request/response bodies (only parsed model fields)
- Authentication tokens (the `public-access-token` is used only for run trace lookup, never stored)
- Account credentials (never passed to the probe worker)

Evidence stored in `model_observations` table is capped at `probe_evidence_cap` (500) items per session, and auto-purged after 7 days.

### 7.3 Network Boundary

- CDP connections are always localhost-only (existing `browser_ws.py` enforces this)
- The probe worker makes NO outbound network requests (it only processes evidence passed to it)
- Run trace resolution (`/api/runs/{id}/trace`) goes through the same browser session — no separate HTTP client
- Temp mail API calls go through the backend's HTTP client with proper timeout and retry

---

## 8. Testing Strategy

### 8.1 Unit Tests

| Component | Coverage Target | Key Tests |
|---|---|---|
| `ArenaAccountService` | 90% | State transitions, encryption round-trip, scheduling, threshold isolation |
| `TemporaryMailProvider` | 85% | Mailbox lifecycle, code extraction regex, timeout handling |
| `ArenaAdapter` | 80% | Selector generation, thinking filter (all 3 modes), error classification |
| `ModelProbeWorker` (Python port) | 90% | Evidence aggregation, UUID mapping, verdict confidence computation |
| `ModelObservationService` | 80% | Persistent session lifecycle, event routing, graceful disconnect |

### 8.2 Integration Tests

- End-to-end registration flow (mock temp mail + mock Arena pages)
- Message dispatch with probe verdict (mock CDP events + verify verdict emission)
- Account isolation threshold (inject N failures → verify state transition)
- Win7 Python port parity (same inputs → same outputs as Node.js worker)

### 8.3 E2E Tests

- Full flow against a test Arena-like server (local fixture)
- CAPTCHA detection and timeout handling
- Browser crash recovery

---

## 9. Phase Breakdown

| Phase | Scope | Effort | Dependencies |
|---|---|---|---|
| **Phase 0** | License audit + source review | 1 day | None |
| **Phase 1** | Pure logic kernel: `classify.py` (Python port), `idmap.py`, `registry.py`, unit tests | 3 days | Phase 0 |
| **Phase 2** | Persistent CDP observer: `cdp_persistent_session()` in `browser_cdp.py`, `ModelObservationService`, Node.js worker bridge | 4 days | Phase 1 |
| **Phase 3** | Arena message automation: `ArenaAdapter` (login, dispatch, Thinking filter, attachment), basic UI panel | 5 days | Phase 2 |
| **Phase 4** | Email + registration: `TemporaryMailProvider`, `MailTMAdapter`, `ArenaAccountService`, registration flow | 4 days | Phase 3 |
| **Phase 5** | Session recovery, optional trace export, Win7 Python port parity verification | 3 days | Phase 4 |

**Total estimated effort:** 20 working days.

---

## 10. File Inventory (New Files)

```
backend/
├── config/
│   └── arena_automation.py            # config model + yaml loader
├── adapters/
│   └── arena.py                       # ArenaAdapter (site-specific automation)
├── services/
│   ├── arena_accounts.py              # ArenaAccountService + SQLite schema
│   ├── model_observation.py           # ModelObservationService
│   ├── temporary_mail/
│   │   ├── __init__.py
│   │   ├── base.py                    # TemporaryMailProvider ABC
│   │   ├── mailtm.py                  # Mail.tm adapter
│   │   ├── guerrilla.py               # Guerrilla Mail adapter
│   │   └── registry.py                # adapter discovery
│   └── model_probe_worker/
│       ├── package.json
│       ├── worker.mjs                 # stdin/stdout JSON bridge
│       └── src/                       # symlinks to arena-model-probe/src/
├── services/model_probe_py/           # Python port (Win7 + fallback)
│   ├── __init__.py
│   ├── classify.py                    # port of classify.js
│   ├── idmap.py                       # port of idmap.js
│   └── registry.py                    # port of registry.js
└── api/
    └── arena_routes.py                # FastAPI routes

electron/
└── arena/
    ├── arenaTaskPanel.ts              # IPC handler
    └── preload-arena.ts               # preload additions

src/
├── components/
│   ├── ArenaTaskPanel.tsx             # main UI surface
│   └── AccountManager.tsx             # account pool CRUD
└── hooks/
    └── useArenaProbe.ts               # React hook for probe events
```

---

## 11. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Arena site structure changes break selectors | Medium | High | Adapter emits `arena:adapter-desync` alert; selectors isolated in config for quick updates |
| CAPTCHA providers add new detection | Low | Medium | System pauses for manual solve; no auto-bypass attempted |
| Node.js unavailable on Win7 | Certain | Low | Python port covers all core logic; Node worker is optimization only |
| CDP persistent connection unstable on Chromium 106 | Low | Medium | Auto-reconnect with backoff; graceful degradation (probe stops, automation continues) |
| Temp mail provider goes offline | Medium | Low | Provider is pluggable; user can switch to alternative or supply own adapter |
| Credential encryption key lost (machine ID changes) | Low | High | Warn user; credentials become unreadable; user must re-register accounts |

---

## 12. Open Questions (Resolved)

| Question | Resolution |
|---|---|
| Which branches? | Both main and release/win7; feature-flagged off by default |
| CAPTCHA/MFA handling? | Manual only — system pauses and waits for user intervention |
| Account pool size? | Configurable, default 5, hard cap at 20 |
| Persistence? | SQLite, cross-restart; credentials encrypted at rest |
| Failure handling? | Isolation + threshold unlock (3 consecutive failures → disabled) |
| Model probe UI? | Only in ArenaTaskPanel — no global model indicator |
| Scheduling? | Serial within account + global concurrency cap (default 2) |
| Win7 constraints? | Strictly Chromium 106; Python port replaces Node.js worker |
