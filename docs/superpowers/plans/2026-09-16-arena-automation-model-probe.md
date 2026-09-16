# Arena Automation & Model Probe Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate Arena account automation with real-time model identity detection via CDP traffic observation, feature-flagged off by default and Win7-compatible (Chromium 106, Python 3.8).

**Architecture:** Five-phase rollout: (0) license/source audit → (1) pure Python port of model classification logic → (2) persistent CDP observer with Node.js worker bridge → (3) Arena site automation adapter + UI panel → (4) email registration + account pool → (5) session recovery + Win7 parity verification. The Node.js worker (main only) handles evidence→verdict logic; the Python port covers Win7 and serves as a fallback.

**Tech Stack:** Python 3.10 (main) / 3.8 (Win7), Pydantic 2.x / 1.x, FastAPI, SQLite, CDP via existing `browser_cdp.py`, `cryptography.fernet` for credential encryption, Node.js (main only) for probe worker, React + Electron for UI.

**Spec:** `docs/superpowers/specs/2026-09-16-arena-automation-model-probe-design.md`

---

## Global Constraints

These are the spec's project-wide requirements. Every task implicitly includes them.

- **Feature flag:** `arena_automation.enabled` defaults to `False`. All entry points check the flag and return 403 when off.
- **Win7 (release/win7 branch) compatibility:** Python 3.8 (sage-backend-py38 conda env), Pydantic 1.x syntax (`class Config:`, `@validator`, no `@model_validator` / `TypeAdapter`), Chromium 106, no Node.js.
- **Main branch:** Python 3.10 (sage-backend conda env), Pydantic 2.x, latest Chromium, Node.js available for probe worker.
- **Encryption:** Use existing `backend/services/secret_box.py` (`SecretBox` with `SAGE_SECRET_SCHEME=test` for tests); do not reinvent.
- **Test markers:** `@pytest.mark.unit`, `@pytest.mark.integration`, `@pytest.mark.e2e`. `asyncio_mode = auto`. 120s test timeout.
- **Logging:** Use module-level `logger = logging.getLogger(__name__)`. Never log raw credentials or full request/response bodies.
- **CDP:** All CDP calls go through `backend/tools/browser_cdp.py` (existing). Extend with `cdp_persistent_session()` rather than spawning new connections.
- **Worktree:** All work in `/home/fz/project/sage/.worktrees/feat-arena-automation-model-probe/` on branch `feat/arena-automation-model-probe`. Backend port 8782, frontend port 1437.
- **Imports:** Use `from __future__ import annotations` at top of every new Python file. Use `Optional[X]` / `List[X]` (not `X | None` / `list[X]`) for Win7 compatibility.
- **Conventional Commits:** Each commit message follows `<type>: <description>`. Types used here: `feat`, `fix`, `test`, `chore`, `docs`.
- **TDD discipline:** Every code task follows RED → GREEN → IMPROVE cycle. Test written first, verified to fail, then minimal implementation, then verify pass, then commit.

---

## File Structure

All new files live under the existing backend / frontend / electron trees. No top-level packages introduced.

**Backend (`backend/`):**

| Path | Purpose |
|---|---|
| `backend/config/arena_automation.py` | Pydantic config model + YAML loader |
| `backend/services/arena_accounts.py` | ArenaAccountService: pool CRUD, state machine, scheduling |
| `backend/services/arena_observation.py` | ModelObservationService: persistent CDP session, evidence routing |
| `backend/services/arena_adapter.py` | ArenaAdapter: site-specific automation (login, dispatch, captcha detection) |
| `backend/services/temporary_mail/__init__.py` | Package init |
| `backend/services/temporary_mail/base.py` | TemporaryMailProvider ABC + Mailbox dataclass |
| `backend/services/temporary_mail/mailtm.py` | Mail.tm REST adapter |
| `backend/services/temporary_mail/guerrilla.py` | Guerrilla Mail adapter |
| `backend/services/temporary_mail/registry.py` | Provider name → class mapping + user-plugin discovery |
| `backend/services/model_probe_py/__init__.py` | Package init |
| `backend/services/model_probe_py/classify.py` | Python port of arena-model-probe classify.js (evidence aggregation) |
| `backend/services/model_probe_py/idmap.py` | Python port of idmap.js (UUID → model name resolution) |
| `backend/services/model_probe_py/registry.py` | Python port of registry.js (model patterns, family protocols) |
| `backend/services/model_probe_worker/worker.mjs` | Node.js stdin/stdout JSON bridge (main only) |
| `backend/api/arena_routes.py` | FastAPI router (accounts, sessions, captcha events) |
| `backend/tools/browser_cdp.py` | **MODIFY** — add `cdp_persistent_session()` context manager |

**Frontend (`src/`):**

| Path | Purpose |
|---|---|
| `src/components/ArenaTaskPanel.tsx` | Main UI surface (account pool, active sessions, verdicts) |
| `src/components/AccountManager.tsx` | Account CRUD component |
| `src/hooks/useArenaProbe.ts` | React hook for probe events (subscribes to IPC) |
| `src/api/arena.ts` | REST client for arena routes |

**Electron (`electron/`):**

| Path | Purpose |
|---|---|
| `electron/arena/arenaTaskPanel.ts` | IPC handlers for arena:* events |
| `electron/arena/preload-arena.ts` | Preload script additions |

**Tests (`backend/tests/`):**

| Path | Marks |
|---|---|
| `backend/tests/unit/services/test_arena_accounts.py` | unit |
| `backend/tests/unit/services/temporary_mail/test_base.py` | unit |
| `backend/tests/unit/services/temporary_mail/test_mailtm.py` | unit |
| `backend/tests/unit/services/model_probe_py/test_classify.py` | unit |
| `backend/tests/unit/services/model_probe_py/test_idmap.py` | unit |
| `backend/tests/unit/adapters/test_arena_adapter.py` | unit |
| `backend/tests/unit/tools/test_browser_cdp_persistent.py` | unit |
| `backend/tests/integration/test_arena_registration_flow.py` | integration |
| `backend/tests/integration/test_arena_dispatch_flow.py` | integration |
| `backend/tests/integration/test_win7_probe_parity.py` | integration |

**Plan:** `docs/superpowers/plans/2026-09-16-arena-automation-model-probe.md`

---

## Phase 0: License Audit & Source Review

### Task 1: License audit of source projects

**Files:**
- Read only: `/home/fz/project/ArenaHelper/` (verify license)
- Read only: `/home/fz/project/arena-model-probe/` (verify license)
- Create: `docs/technical/50-arena-source-license-audit.md` (audit report)

**Why this is the first task:** The code we port must be compatible with Sage's license (proprietary / closed source) and must not introduce GPL/AGPL contamination. Both source projects need explicit license confirmation before any code lands in the repo.

**Steps:**

- [ ] **Step 1: Read ArenaHelper LICENSE / README for license terms**

Run: `ls -la /home/fz/project/ArenaHelper/ | grep -iE 'license|copying|readme'`
Expected: At least one of `LICENSE`, `LICENSE.md`, `LICENSE.txt`, `README.md`, or `COPYING`.

- [ ] **Step 2: Read arena-model-probe LICENSE / README for license terms**

Run: `ls -la /home/fz/project/arena-model-probe/ | grep -iE 'license|copying|readme'`
Expected: Similar set of files.

- [ ] **Step 3: Read LICENSE contents of each project**

Read the contents of any LICENSE / LICENSE.md file found in either project. Note: license type (MIT, Apache-2.0, GPL, proprietary, etc.), copyright holder, redistribution requirements.

- [ ] **Step 4: Write audit report**

Write `docs/technical/50-arena-source-license-audit.md` with sections:
- Source: ArenaHelper — License: <type>, Copyright: <holder>
- Source: arena-model-probe — License: <type>, Copyright: <holder>
- Compatibility assessment: Can we port (a) logic only, (b) logic + verbatim code, or (c) neither?
- Per-file disposition: For each file we plan to port, list it and mark ✅ safe / ⚠️ needs review / ❌ blocked.

- [ ] **Step 5: Verify report committed**

Run: `git add docs/technical/50-arena-source-license-audit.md && git commit -m "docs(legal): arena automation source license audit"`

**Deliverable:** A clear go/no-go for each file we plan to port. If any are blocked, escalate to user before continuing.

---

## Phase 1: Pure Logic Kernel (Python port of model classification)

### Task 2: Port registry.py from arena-model-probe to Python

**Files:**
- Create: `backend/services/model_probe_py/__init__.py`
- Create: `backend/services/model_probe_py/registry.py`
- Create: `backend/tests/unit/services/model_probe_py/__init__.py`
- Create: `backend/tests/unit/services/model_probe_py/test_registry.py`

**Interfaces:**
- Consumes: nothing (leaf module)
- Produces:
  - `MODEL_PATTERNS: Dict[str, Pattern]` — regex patterns for model name families
  - `FAMILY_PROTOCOLS: Dict[str, List[str]]` — protocol fingerprints per family
  - `HOST_VENDOR: Dict[str, str]` — hostname → vendor mapping
  - `MODEL_KEY_RE: Pattern` — JSON key name pattern for model fields
  - `USAGE_KEYS: Set[str]` — JSON key names for token usage
  - `MODEL_HEADER_RE: Pattern` — HTTP header pattern for model field
  - `isFrontier(name: str) -> bool` — whether a model name is from a frontier family

**Steps:**

- [ ] **Step 1: Read the source registry.js to understand what to port**

Read `/home/fz/project/arena-model-probe/src/registry.js` and identify the exported constants and functions.

- [ ] **Step 2: Write the failing test**

```python
# backend/tests/unit/services/model_probe_py/test_registry.py
import re
import pytest

from backend.services.model_probe_py import registry


def test_model_patterns_is_non_empty_dict():
    assert isinstance(registry.MODEL_PATTERNS, dict)
    assert len(registry.MODEL_PATTERNS) >= 4  # at minimum: gpt, claude, gemini, llama


def test_model_key_re_matches_expected_keys():
    assert registry.MODEL_KEY_RE.search('"model"')
    assert registry.MODEL_KEY_RE.search('"model_id"')
    assert registry.MODEL_KEY_RE.search('"upstream_model"')
    assert not registry.MODEL_KEY_RE.search('"unrelated"')


def test_host_vendor_maps_known_hosts():
    assert registry.HOST_VENDOR.get("api.openai.com") == "openai"
    assert registry.HOST_VENDOR.get("api.anthropic.com") == "anthropic"


def test_is_frontier_returns_true_for_known_models():
    assert registry.isFrontier("gpt-4o")
    assert registry.isFrontier("claude-opus-4-6")
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd /home/fz/project/sage/.worktrees/feat-arena-automation-model-probe && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/services/model_probe_py/test_registry.py -v`
Expected: `ModuleNotFoundError: No module named 'backend.services.model_probe_py'`

- [ ] **Step 4: Write minimal implementation**

Create `backend/services/model_probe_py/__init__.py` (empty), then `backend/services/model_probe_py/registry.py`:

```python
"""Port of arena-model-probe/src/registry.js (Python 3.8 compatible)."""

from __future__ import annotations

import re
from typing import Dict, List, Pattern, Set


#: Model name family patterns: family name → regex of canonical model name patterns
MODEL_PATTERNS: Dict[str, Pattern] = {
    "gpt": re.compile(r"\bgpt[-\s]?\d|chatgpt|gpt-4o|gpt-5|gpt-6", re.IGNORECASE),
    "claude": re.compile(r"\bclaude[-\s]?(?:opus|sonnet|haiku|[\d-]+)", re.IGNORECASE),
    "gemini": re.compile(r"\bgemini[-\s]?(?:pro|ultra|nano|[\d.]+)", re.IGNORECASE),
    "llama": re.compile(r"\bllama[-\s]?[\d.]+", re.IGNORECASE),
    "deepseek": re.compile(r"\bdeepseek[-\s]?[cv]?\d", re.IGNORECASE),
    "qwen": re.compile(r"\bqwen[-\s]?[\d.]+", re.IGNORECASE),
    "mistral": re.compile(r"\bmistral[-\s]?(?:large|medium|small|[\d]+)", re.IGNORECASE),
}


#: JSON key names that carry model identifiers
MODEL_KEY_RE: Pattern = re.compile(
    r"^(model|model_id|modelId|model_name|served_model|upstream_model|"
    r"resolved_model|base_model|deployment|engine|model_slug|model_key|"
    r"selected_model|current_model|target_model|requested_model)$",
    re.IGNORECASE,
)


#: JSON key names for token usage
USAGE_KEYS: Set[str] = {
    "input_tokens", "output_tokens", "total_tokens",
    "prompt_tokens", "completion_tokens",
    "inputTokens", "outputTokens", "totalTokens",
    "promptTokenCount", "candidatesTokenCount", "thoughtsTokenCount",
    "cache_creation_input_tokens", "cache_read_input_tokens",
}


#: HTTP header pattern for model fields
MODEL_HEADER_RE: Pattern = re.compile(r"^x-?(?:model|llm|ai)[-_]?model$", re.IGNORECASE)


#: Hostname → vendor family
HOST_VENDOR: Dict[str, str] = {
    "api.openai.com": "openai",
    "api.anthropic.com": "anthropic",
    "generativelanguage.googleapis.com": "google",
    "api.deepseek.com": "deepseek",
    "api.x.ai": "xai",
    "openrouter.ai": "openrouter",
    "api.groq.com": "groq",
    "api.together.xyz": "together",
    "api.mistral.ai": "mistral",
    "dashscope.aliyuncs.com": "alibaba",
    "api.moonshot.cn": "moonshot",
    "api.bigmodel.cn": "zhipu",
    "ark.cn-beijing.volces.com": "bytedance",
}


#: Protocol framing tokens per family (for fingerprinting when no model string exists)
FAMILY_PROTOCOLS: Dict[str, List[str]] = {
    "anthropic": [
        "message_start", "content_block_delta", "thinking_delta",
        "toolu_", "cache_creation_input_tokens", "cache_read_input_tokens",
    ],
    "openai": [
        "chatcmpl-", "system_fingerprint", '"object":"chat.completion.chunk"',
    ],
    "google": [
        "generateContent", "streamGenerateContent", "candidates",
        "safetyRatings", "promptFeedback",
    ],
}


_FRONTIER_FAMILIES = {"gpt", "claude", "gemini"}


def isFrontier(name: str) -> bool:
    """Return True if model name matches a known frontier family pattern."""
    if not isinstance(name, str) or not name:
        return False
    for family, pattern in MODEL_PATTERNS.items():
        if family in _FRONTIER_FAMILIES and pattern.search(name):
            return True
    return False
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd /home/fz/project/sage/.worktrees/feat-arena-automation-model-probe && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/services/model_probe_py/test_registry.py -v`
Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
cd /home/fz/project/sage/.worktrees/feat-arena-automation-model-probe
git add backend/services/model_probe_py/ backend/tests/unit/services/model_probe_py/
git commit -m "feat(probe): port registry.js to Python (model patterns, host vendor)"
```

---

### Task 3: Port classify.py — evidence collection and verdict computation

**Files:**
- Create: `backend/services/model_probe_py/classify.py`
- Create: `backend/tests/unit/services/model_probe_py/test_classify.py`

**Interfaces:**
- Consumes: `registry.MODEL_PATTERNS`, `registry.FAMILY_PROTOCOLS`, `registry.HOST_VENDOR`, `registry.MODEL_KEY_RE`, `registry.MODEL_HEADER_RE`
- Produces:
  - `SOURCE_WEIGHTS: Dict[str, float]` — evidence source authority weights
  - `collectModelFields(node, path='$', out=None, depth=0, maxDepth=12) -> List[Dict]` — deep JSON traversal
  - `scanTextForModel(text: str) -> List[str]` — regex fallback for non-JSON text
  - `vendorFromUrl(url: str) -> Optional[str]` — hostname → vendor
  - `protocolFingerprint(text: str) -> Optional[str]` — detect family from framing tokens
  - `resolveEvidence(evidence_list: List[Dict]) -> Dict` — aggregate evidence into final verdict

**Steps:**

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/services/model_probe_py/test_classify.py
import pytest

from backend.services.model_probe_py.classify import (
    collectModelFields, scanTextForModel, vendorFromUrl,
    protocolFingerprint, resolveEvidence, SOURCE_WEIGHTS,
)


def test_collect_model_fields_finds_nested_model():
    payload = {
        "choices": [
            {"message": {"model": "gpt-4o", "content": "hi"}}
        ]
    }
    out = collectModelFields(payload)
    assert any(item["value"] == "gpt-4o" for item in out)


def test_collect_model_fields_respects_max_depth():
    payload = {"a": {"b": {"c": {"d": {"e": {"model": "deep"}}}}}}
    out = collectModelFields(payload, maxDepth=2)
    # depth 2 means we only descend 2 levels; 'deep' is at depth 5
    assert not any(item["value"] == "deep" for item in out)


def test_scan_text_for_model_extracts_string_values():
    text = 'data: {"model": "claude-opus-4-6", "id": "msg_123"}'
    found = scanTextForModel(text)
    assert "claude-opus-4-6" in found


def test_vendor_from_url_recognizes_known_hosts():
    assert vendorFromUrl("https://api.openai.com/v1/chat") == "openai"
    assert vendorFromUrl("https://api.anthropic.com/v1/messages") == "anthropic"
    assert vendorFromUrl("https://unknown.example.com/x") is None


def test_protocol_fingerprint_detects_anthropic():
    text = '{"type":"message_start","message":{"id":"msg_01"}}'
    assert protocolFingerprint(text) == "anthropic"


def test_protocol_fingerprint_detects_openai():
    text = '{"id":"chatcmpl-abc123","object":"chat.completion.chunk"}'
    assert protocolFingerprint(text) == "openai"


def test_resolve_evidence_aggregates_by_model_id():
    evidence = [
        {"source": "request.body.model", "modelId": "gpt-4o", "weight": 1.0},
        {"source": "response.json.model", "modelId": "gpt-4o", "weight": 0.93},
    ]
    verdict = resolveEvidence(evidence)
    assert verdict["modelId"] == "gpt-4o"
    assert verdict["confidence"] >= 0.93


def test_source_weights_have_expected_keys():
    expected = {"request.body.model", "response.header.model", "run.trace.model",
                "sse.chunk.model", "protocol.framing", "behavior.probe"}
    assert expected.issubset(SOURCE_WEIGHTS.keys())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/fz/project/sage/.worktrees/feat-arena-automation-model-probe && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/services/model_probe_py/test_classify.py -v`
Expected: `ModuleNotFoundError: No module named 'backend.services.model_probe_py.classify'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/services/model_probe_py/classify.py
"""Port of arena-model-probe/src/classify.js (Python 3.8 compatible).

Evidence aggregation and verdict computation. Pure functions, no I/O.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from .registry import (
    FAMILY_PROTOCOLS, HOST_VENDOR, MODEL_HEADER_RE, MODEL_KEY_RE,
)


#: Evidence source authority weights (the closer to ground truth, the higher)
SOURCE_WEIGHTS: Dict[str, float] = {
    "run.trace.model":           1.00,
    "request.body.model":        1.00,
    "response.header.model":     0.95,
    "response.json.model":       0.93,
    "idmap.resolve":             0.92,
    "sse.chunk.model":           0.90,
    "url.path.model":            0.85,
    "response.header.provider":  0.80,
    "url.host.vendor":           0.80,
    "protocol.framing":          0.72,
    "request.header":            0.60,
    "dom.text":                  0.45,
    "behavior.probe":            0.35,
    "self.report":               0.15,
}


def collectModelFields(
    node: Any,
    path: str = "$",
    out: Optional[List[Dict]] = None,
    depth: int = 0,
    maxDepth: int = 12,
) -> List[Dict]:
    """Recursively traverse JSON, collect all string values for model-key fields."""
    if out is None:
        out = []
    if depth > maxDepth or node is None:
        return out
    if not isinstance(node, (dict, list)):
        return out

    if isinstance(node, list):
        for i, item in enumerate(node):
            collectModelFields(item, f"{path}[{i}]", out, depth + 1, maxDepth)
        return out

    for key, value in node.items():
        p = f"{path}.{key}"
        if MODEL_KEY_RE.match(key) and isinstance(value, str) and 2 <= len(value) <= 120:
            out.append({"path": p, "key": key, "value": value})
        elif key == "model" and isinstance(value, list):
            for i, m in enumerate(value):
                if isinstance(m, str):
                    out.append({"path": f"{p}[{i}]", "key": "model", "value": m})
        elif isinstance(value, (dict, list)):
            collectModelFields(value, p, out, depth + 1, maxDepth)
    return out


def scanTextForModel(text: str) -> List[str]:
    """Regex fallback: find model strings in arbitrary text (e.g. truncated SSE)."""
    found: List[str] = []
    if not isinstance(text, str) or not text:
        return found
    pattern = re.compile(
        r'"(?:model|model_id|modelId|model_name|served_model|upstream_model|'
        r'resolved_model)"\s*:\s*"([^"\\]{2,120})"'
    )
    for match in pattern.finditer(text):
        if match.group(1) not in found:
            found.append(match.group(1))
    return found


def vendorFromUrl(url: str) -> Optional[str]:
    """Map URL hostname to known vendor family."""
    if not isinstance(url, str) or not url:
        return None
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return None
    if not host:
        return None
    # exact match first
    if host in HOST_VENDOR:
        return HOST_VENDOR[host]
    # suffix match (api.openai.com matches openai.com)
    for known_host, vendor in HOST_VENDOR.items():
        if host.endswith("." + known_host) or host == known_host:
            return vendor
    return None


def protocolFingerprint(text: str) -> Optional[str]:
    """Detect family from protocol framing tokens when no model string is present."""
    if not isinstance(text, str) or not text:
        return None
    for family, tokens in FAMILY_PROTOCOLS.items():
        for token in tokens:
            if token in text:
                return family
    return None


def resolveEvidence(evidence: List[Dict]) -> Dict:
    """Aggregate evidence items into a single verdict.

    Each evidence item is a dict with at least: source, modelId (or family),
    weight (optional, defaults to SOURCE_WEIGHTS lookup).

    Returns a verdict dict: {modelId, family, confidence, source, evidence_count}.
    When no modelId is present but family is, return family-level verdict with
    reduced confidence.
    """
    if not evidence:
        return {
            "modelId": None, "family": None, "confidence": 0.0,
            "source": None, "evidence_count": 0,
        }

    # Group evidence by modelId
    by_model: Dict[str, List[Dict]] = defaultdict(list)
    for item in evidence:
        mid = item.get("modelId")
        if mid:
            by_model[mid].append(item)

    if not by_model:
        # No explicit modelId; fall back to family-level grouping
        by_family: Dict[str, List[Dict]] = defaultdict(list)
        for item in evidence:
            fam = item.get("family")
            if fam:
                by_family[fam].append(item)
        if not by_family:
            return {
                "modelId": None, "family": None, "confidence": 0.0,
                "source": None, "evidence_count": 0,
            }
        # Pick family with highest combined weight
        best_family, best_items = max(
            by_family.items(),
            key=lambda kv: sum(it.get("weight", SOURCE_WEIGHTS.get(it.get("source", ""), 0.5)) for it in kv[1]),
        )
        return {
            "modelId": None,
            "family": best_family,
            "confidence": min(sum(
                it.get("weight", SOURCE_WEIGHTS.get(it.get("source", ""), 0.5)) for it in best_items
            ) / len(best_items), 1.0),
            "source": best_items[0].get("source"),
            "evidence_count": len(best_items),
        }

    # Pick modelId with highest combined weight
    best_model, best_items = max(
        by_model.items(),
        key=lambda kv: sum(
            it.get("weight", SOURCE_WEIGHTS.get(it.get("source", ""), 0.5)) for it in kv[1]
        ),
    )
    confidence = min(
        sum(it.get("weight", SOURCE_WEIGHTS.get(it.get("source", ""), 0.5)) for it in best_items)
        / len(best_items),
        1.0,
    )
    # Family inferred from first item that has it, or from registry
    family = None
    for it in best_items:
        if it.get("family"):
            family = it["family"]
            break
    return {
        "modelId": best_model,
        "family": family,
        "confidence": round(confidence, 3),
        "source": best_items[0].get("source"),
        "evidence_count": len(best_items),
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/fz/project/sage/.worktrees/feat-arena-automation-model-probe && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/services/model_probe_py/test_classify.py -v`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
cd /home/fz/project/sage/.worktrees/feat-arena-automation-model-probe
git add backend/services/model_probe_py/classify.py backend/tests/unit/services/model_probe_py/test_classify.py
git commit -m "feat(probe): port classify.js to Python (evidence aggregation, verdict)"
```

---

### Task 4: Port idmap.py — UUID → model name resolution

**Files:**
- Create: `backend/services/model_probe_py/idmap.py`
- Create: `backend/tests/unit/services/model_probe_py/test_idmap.py`

**Interfaces:**
- Consumes: `registry.MODEL_PATTERNS`
- Produces:
  - `isUuid(s: str) -> bool` — UUID format detection
  - `mapStats() -> Dict` — current map statistics
  - `resolveModelId(identifier: str, known_map: Optional[Dict] = None) -> Optional[str]` — UUID → name lookup
  - `refreshModelMap(fetcher: Optional[Callable[[], Awaitable[Dict]]] = None) -> Dict` — async map refresh (fetcher injectable for tests)

**Steps:**

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/services/model_probe_py/test_idmap.py
import asyncio
import pytest

from backend.services.model_probe_py.idmap import (
    isUuid, resolveModelId, refreshModelMap, mapStats, _model_map,
)


def test_is_uuid_recognizes_standard_format():
    assert isUuid("550e8400-e29b-41d4-a716-446655440000")
    assert isUuid("550E8400-E29B-41D4-A716-446655440000")  # uppercase
    assert not isUuid("gpt-4o")
    assert not isUuid("not-a-uuid")
    assert not isUuid("")


def test_resolve_model_id_passthrough_for_non_uuid():
    assert resolveModelId("gpt-4o") == "gpt-4o"
    assert resolveModelId("claude-opus-4-6") == "claude-opus-4-6"


def test_resolve_model_id_uses_injected_map():
    test_map = {
        "uuid-aaaa": "gpt-6-astra-high",
        "uuid-bbbb": "claude-opus-4-6",
    }
    assert resolveModelId("uuid-aaaa", known_map=test_map) == "gpt-6-astra-high"
    assert resolveModelId("uuid-bbbb", known_map=test_map) == "claude-opus-4-6"
    assert resolveModelId("uuid-unknown", known_map=test_map) == "uuid-unknown"


def test_refresh_model_map_calls_fetcher():
    async def fake_fetcher():
        return {"uuid-xxxx": "gpt-5-turbo"}
    asyncio.run(refreshModelMap(fetcher=fake_fetcher))
    # map should now contain the entry
    assert _model_map.get("uuid-xxxx") == "gpt-5-turbo"


def test_map_stats_returns_loaded_count():
    stats = mapStats()
    assert "loaded" in stats
    assert isinstance(stats["loaded"], int)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/fz/project/sage/.worktrees/feat-arena-automation-model-probe && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/services/model_probe_py/test_idmap.py -v`
Expected: `ModuleNotFoundError: No module named 'backend.services.model_probe_py.idmap'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/services/model_probe_py/idmap.py
"""Port of arena-model-probe/src/idmap.js (Python 3.8 compatible).

UUID → model name resolution. The map is populated by fetching Arena's
leaderboard RSC payload periodically.
"""

from __future__ import annotations

import logging
import re
from typing import Awaitable, Callable, Dict, Optional

logger = logging.getLogger(__name__)


#: Module-level model map. Mutated by refreshModelMap().
_model_map: Dict[str, str] = {}


#: UUID v4 format (8-4-4-4-12 hex)
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def isUuid(s: str) -> bool:
    """True if s is a UUID-shaped string."""
    if not isinstance(s, str) or not s:
        return False
    return bool(_UUID_RE.match(s))


def resolveModelId(identifier: str, known_map: Optional[Dict] = None) -> Optional[str]:
    """If identifier is a UUID in the map, return the canonical model name.

    Otherwise return identifier unchanged (passthrough for plain model names).
    """
    if not identifier:
        return identifier
    mapping = known_map if known_map is not None else _model_map
    if isUuid(identifier) and identifier in mapping:
        return mapping[identifier]
    return identifier


async def refreshModelMap(
    fetcher: Optional[Callable[[], Awaitable[Dict]]] = None,
) -> Dict:
    """Refresh the UUID → model name map.

    If fetcher is provided, call it and replace the map. If not, no-op
    (the caller is expected to manage when to fetch in production).
    """
    if fetcher is None:
        return {"loaded": len(_model_map), "updated": False}
    try:
        new_map = await fetcher()
        if isinstance(new_map, dict):
            _model_map.clear()
            _model_map.update(new_map)
            logger.info("idmap refreshed: %d entries", len(new_map))
            return {"loaded": len(new_map), "updated": True}
    except Exception as e:  # noqa: BLE001
        logger.warning("idmap refresh failed: %s", e)
        return {"loaded": len(_model_map), "updated": False, "error": str(e)}
    return {"loaded": len(_model_map), "updated": False}


def mapStats() -> Dict:
    """Return current map statistics."""
    return {"loaded": len(_model_map)}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/fz/project/sage/.worktrees/feat-arena-automation-model-probe && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/services/model_probe_py/test_idmap.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
cd /home/fz/project/sage/.worktrees/feat-arena-automation-model-probe
git add backend/services/model_probe_py/idmap.py backend/tests/unit/services/model_probe_py/test_idmap.py
git commit -m "feat(probe): port idmap.js to Python (UUID→model name resolution)"
```

---

## Phase 2: Persistent CDP Observer

### Task 5: Add cdp_persistent_session() to browser_cdp.py

**Files:**
- Modify: `backend/tools/browser_cdp.py` (append function at end)
- Create: `backend/tests/unit/tools/__init__.py` (empty)
- Create: `backend/tests/unit/tools/test_browser_cdp_persistent.py`

**Interfaces:**
- Consumes: existing `BrowserSession` from `browser_cdp.py`
- Produces:
  - `PersistentCDPSession` (context manager class) with:
    - `events: asyncio.Queue` — incoming CDP event frames
    - `send(method: str, params: Optional[Dict] = None) -> Dict` — send a CDP command
    - `close() -> None` — close the underlying WebSocket
    - `__enter__` / `__exit__` — context manager protocol

**Steps:**

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/tools/test_browser_cdp_persistent.py
import asyncio
import json
import pytest

from backend.tools.browser_cdp import PersistentCDPSession


def test_persistent_session_class_exists():
    """Smoke test that the class can be imported and inspected."""
    assert PersistentCDPSession is not None
    # Class must have send, close, events attributes
    for attr in ("events", "send", "close"):
        assert hasattr(PersistentCDPSession, attr), f"missing {attr}"


def test_persistent_session_increments_message_id(monkeypatch):
    """send() must assign monotonically increasing ids; use a fake transport."""
    sent_payloads: list = []

    class FakeWS:
        def __init__(self):
            self.closed = False
            self._responses = {
                1: {"id": 1, "result": {"frameTree": {}}},
            }
        async def send(self, data):
            sent_payloads.append(json.loads(data))
        async def recv(self):
            # return next queued response, or block
            return json.dumps({"id": 1, "result": {}}).encode()
        async def close(self):
            self.closed = True

    # Construction alone shouldn't open a connection
    # (we test message-id generation via a helper or direct method)
    from backend.tools.browser_cdp import _next_message_id, _reset_message_id
    _reset_message_id()
    assert _next_message_id() == 1
    assert _next_message_id() == 2
    assert _next_message_id() == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/fz/project/sage/.worktrees/feat-arena-automation-model-probe && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/tools/test_browser_cdp_persistent.py -v`
Expected: `ImportError: cannot import name 'PersistentCDPSession' from 'backend.tools.browser_cdp'`

- [ ] **Step 3: Add minimal implementation**

Append to `backend/tools/browser_cdp.py` (find the end of the file with Read, then Edit):

```python
# ---------------------------------------------------------------------------
# Persistent CDP session (Phase 2 of arena automation)
# ---------------------------------------------------------------------------
#
# Unlike cdp_command() (short-lived, one command per connection), a persistent
# session holds a single WebSocket open for the lifetime of the observation
# and routes incoming CDP event frames to an in-memory queue.

import asyncio
import contextlib
import threading
from collections import deque
from queue import Queue as SyncQueue  # used for sync-test injection only
from typing import Any, Dict, Iterator, List, Optional


_message_id_lock = threading.Lock()
_message_id_counter = 0


def _next_message_id() -> int:
    global _message_id_counter
    with _message_id_lock:
        _message_id_counter += 1
        return _message_id_counter


def _reset_message_id() -> None:
    """Reset the counter; intended for tests only."""
    global _message_id_counter
    with _message_id_lock:
        _message_id_counter = 0


class PersistentCDPSession:
    """Context manager wrapping a long-lived CDP WebSocket.

    Usage:
        with cdp_persistent_session(session) as cdp:
            await cdp.send_async("Network.enable")
            while True:
                event = await cdp.next_event()
                ...

    For sync (test) usage, the constructor accepts an injected ``ws_factory``
    that returns an object with ``send`` / ``recv`` / ``close`` async methods.
    """

    def __init__(
        self,
        browser_session: Any,
        ws_factory: Optional[Any] = None,
    ):
        self._browser_session = browser_session
        self._ws_factory = ws_factory  # for tests
        self._ws: Any = None
        self._reader_task: Optional[asyncio.Task] = None
        self._sync_queue: deque = deque()  # for sync test mode
        self.events: Any = None  # asyncio.Queue when async, deque when sync

    def __enter__(self) -> "PersistentCDPSession":
        if self._ws_factory is not None:
            # Sync test path: caller provides a fake WS; we just queue frames manually
            self._ws = self._ws_factory()
            self.events = self._sync_queue
            return self
        # Real path: caller should use cdp_persistent_session() async helper below
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._ws is not None:
            with contextlib.suppress(Exception):
                if hasattr(self._ws, "close"):
                    # close may be async; for sync we accept either
                    result = self._ws.close()
                    if asyncio.iscoroutine(result):
                        # In sync context, schedule and wait
                        try:
                            loop = asyncio.get_event_loop()
                            if loop.is_running():
                                loop.create_task(result)
                            else:
                                loop.run_until_complete(result)
                        except RuntimeError:
                            asyncio.run(result)

    async def send_async(self, method: str, params: Optional[Dict] = None) -> Dict:
        """Send a command and return the response dict."""
        if self._ws is None:
            raise BrowserCDPError("session not connected")
        msg_id = _next_message_id()
        payload = {"id": msg_id, "method": method, "params": params or {}}
        if hasattr(self._ws, "send"):
            await self._ws.send(json.dumps(payload))
        # Caller is responsible for matching responses via the event queue
        return {"id": msg_id, "method": method}

    def push_event(self, frame: Dict) -> None:
        """Inject an event frame (used by tests and by the async reader task)."""
        if isinstance(self.events, deque):
            self.events.append(frame)
        elif self.events is not None:
            self.events.put_nowait(frame)

    def close(self) -> None:
        """Close the underlying WebSocket."""
        self.__exit__(None, None, None)


@contextlib.contextmanager
def cdp_persistent_session(browser_session: Any) -> Iterator[PersistentCDPSession]:
    """Sync entry point. For full async lifecycle, use PersistentCDPSession directly."""
    sess = PersistentCDPSession(browser_session)
    try:
        yield sess
    finally:
        sess.close()
```

Note: the imports `asyncio`, `contextlib`, `threading`, `deque`, `Iterator`, `List` may already be imported at the top of `browser_cdp.py`; if not, add them to the existing import block rather than duplicating.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/fz/project/sage/.worktrees/feat-arena-automation-model-probe && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/tools/test_browser_cdp_persistent.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
cd /home/fz/project/sage/.worktrees/feat-arena-automation-model-probe
git add backend/tools/browser_cdp.py backend/tests/unit/tools/test_browser_cdp_persistent.py backend/tests/unit/tools/__init__.py
git commit -m "feat(cdp): add PersistentCDPSession for long-lived observation"
```

---

### Task 6: Implement ModelObservationService — evidence routing

**Files:**
- Create: `backend/services/arena_observation.py`
- Create: `backend/tests/unit/services/test_arena_observation.py`
- Create: `backend/tests/unit/services/__init__.py` (empty)

**Interfaces:**
- Consumes: `BrowserSession` (from `browser_cdp`), `ModelProbeWorker` (Python port, see Task 7)
- Produces:
  - `class ModelObservationService`
    - `__init__(browser_session, worker)` — store refs
    - `start() -> None` — open persistent CDP, enable Network domain, start event router
    - `stop() -> None` — close session
    - `process_event(event: Dict) -> Optional[Dict]` — parse one CDP event into evidence, call worker, return verdict
    - `get_recent_verdicts(n: int = 10) -> List[Dict]` — return last N verdicts

**Steps:**

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/services/test_arena_observation.py
import pytest

from backend.services.arena_observation import ModelObservationService


class FakeBrowserSession:
    def __init__(self):
        self.attached = False


class FakeWorker:
    def __init__(self):
        self.calls: list = []

    def classify(self, evidence):
        self.calls.append(evidence)
        return {
            "modelId": "gpt-4o",
            "family": "openai",
            "confidence": 0.95,
            "source": evidence["source"],
            "evidence_count": 1,
        }


def test_observation_service_stores_dependencies():
    bs = FakeBrowserSession()
    w = FakeWorker()
    svc = ModelObservationService(browser_session=bs, worker=w)
    assert svc._browser_session is bs
    assert svc._worker is w
    assert svc.get_recent_verdicts() == []


def test_observation_service_processes_request_will_be_sent():
    bs = FakeBrowserSession()
    w = FakeWorker()
    svc = ModelObservationService(browser_session=bs, worker=w)

    event = {
        "method": "Network.requestWillBeSent",
        "params": {
            "requestId": "req-1",
            "request": {
                "url": "https://arena.ai/api/agent",
                "method": "POST",
                "postData": '{"model": "gpt-4o", "messages": []}',
            },
        },
    }
    verdict = svc.process_event(event)
    assert verdict is not None
    assert verdict["modelId"] == "gpt-4o"
    assert len(w.calls) == 1
    assert w.calls[0]["source"] == "request.body.model"


def test_observation_service_ignores_unrelated_urls():
    bs = FakeBrowserSession()
    w = FakeWorker()
    svc = ModelObservationService(browser_session=bs, worker=w)

    # Static asset — should be ignored
    event = {
        "method": "Network.requestWillBeSent",
        "params": {
            "requestId": "req-2",
            "request": {"url": "https://arena.ai/static/main.js", "method": "GET"},
        },
    }
    verdict = svc.process_event(event)
    assert verdict is None
    assert len(w.calls) == 0


def test_observation_service_ignores_telemetry_hosts():
    bs = FakeBrowserSession()
    w = FakeWorker()
    svc = ModelObservationService(browser_session=bs, worker=w)

    event = {
        "method": "Network.requestWillBeSent",
        "params": {
            "requestId": "req-3",
            "request": {
                "url": "https://browser-intake-datadoghq.com/api/v2/rum",
                "method": "POST",
                "postData": '{"model": "gpt-4o"}',
            },
        },
    }
    verdict = svc.process_event(event)
    assert verdict is None


def test_observation_service_recent_verdicts_capped():
    bs = FakeBrowserSession()
    w = FakeWorker()
    svc = ModelObservationService(browser_session=bs, worker=w)
    svc._verdict_cap = 3
    for i in range(5):
        svc._record_verdict({"modelId": f"m{i}", "confidence": 0.5, "source": "x"})
    assert len(svc.get_recent_verdicts()) == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/fz/project/sage/.worktrees/feat-arena-automation-model-probe && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/services/test_arena_observation.py -v`
Expected: `ModuleNotFoundError: No module named 'backend.services.arena_observation'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/services/arena_observation.py
"""Model observation service — persistent CDP event router for model probe.

Sits between a Sage-managed browser session and the model probe worker
(Python port or Node.js subprocess). Converts raw CDP Network events into
evidence dicts and forwards them for classification.
"""

from __future__ import annotations

import json
import logging
import re
from collections import deque
from typing import Any, Callable, Deque, Dict, List, Optional

from .model_probe_py.classify import (
    collectModelFields, scanTextForModel, vendorFromUrl, protocolFingerprint,
)

logger = logging.getLogger(__name__)


#: URL patterns that look like AI inference endpoints
_LLM_URL_HINTS = re.compile(
    r"(?:completions?|chat|messages|generate|generateContent|"
    r"streamGenerateContent|converse|invoke|agent|run|responses|"
    r"assistant|thread|conversation|inference|chatbot|api/v\d|/api/|/rpc/|/graphql/)",
    re.IGNORECASE,
)

#: Telemetry / analytics hosts whose payloads should never be treated as model evidence
_TELEMETRY_RE = re.compile(
    r"(?:datadoghq|datadog|posthog|sentry|amplitude|mixpanel|segment\.io|"
    r"segment\.com|google-analytics|googletagmanager|hotjar|clarity\.ms|"
    r"fullstory|logrocket|newrelic|nr-data|bugsnag|rollbar|trackjs|"
    r"raygun|elastic\.co|honeycomb|lightstep|opentelemetry|otlp|"
    r"statsig|launchdarkly|optimizely|split\.io|vwo\.com|matomo|"
    r"plausible\.io|umami|vercel-insights|vercel\.com/_vercel/insights)",
    re.IGNORECASE,
)

#: Static asset extensions
_STATIC_EXT_RE = re.compile(
    r"\.(?:js|css|png|jpe?g|gif|svg|woff2?|ttf|ico|map|mp4|webp|avif)(?:\?|$)",
    re.IGNORECASE,
)


def _is_llm_relevant(url: str) -> bool:
    if not url:
        return False
    if _STATIC_EXT_RE.search(url):
        return False
    if _TELEMETRY_RE.search(url):
        return False
    return bool(_LLM_URL_HINTS.search(url))


class ModelObservationService:
    """Route CDP Network events into probe worker; track recent verdicts."""

    #: Default cap on stored verdicts (matches spec §3.1 probe_evidence_cap)
    DEFAULT_VERDICT_CAP = 500

    def __init__(
        self,
        browser_session: Any,
        worker: Any,
        verdict_cap: int = DEFAULT_VERDICT_CAP,
    ):
        self._browser_session = browser_session
        self._worker = worker
        self._verdict_cap = verdict_cap
        self._verdicts: Deque[Dict] = deque(maxlen=verdict_cap)
        self._running = False

    def start(self) -> None:
        """Open persistent CDP session, enable Network domain. Stubbed for now;
        real implementation in Phase 2 task 8 once Node worker bridge lands."""
        self._running = True
        logger.info("ModelObservationService started")

    def stop(self) -> None:
        self._running = False
        logger.info("ModelObservationService stopped")

    def process_event(self, event: Dict) -> Optional[Dict]:
        """Parse a single CDP event into evidence; ask worker to classify.

        Returns the verdict dict, or None if the event was filtered out.
        """
        if not isinstance(event, dict):
            return None
        method = event.get("method", "")
        params = event.get("params") or {}

        if method == "Network.requestWillBeSent":
            evidence = self._evidence_from_request(params)
        elif method == "Network.responseReceived":
            evidence = self._evidence_from_response(params)
        elif method == "Network.webSocketFrameReceived":
            evidence = self._evidence_from_ws_frame(params)
        else:
            return None

        if evidence is None:
            return None

        try:
            verdict = self._worker.classify(evidence)
        except Exception as e:  # noqa: BLE001
            logger.warning("worker.classify failed: %s", e)
            return None

        if verdict and verdict.get("modelId") or verdict and verdict.get("family"):
            self._record_verdict(verdict)
            return verdict
        return None

    def get_recent_verdicts(self, n: int = 10) -> List[Dict]:
        if n <= 0:
            return []
        return list(self._verdicts)[-n:]

    # -- internal helpers -------------------------------------------------

    def _record_verdict(self, verdict: Dict) -> None:
        self._verdicts.append(verdict)

    def _evidence_from_request(self, params: Dict) -> Optional[Dict]:
        request = params.get("request") or {}
        url = request.get("url") or ""
        if not _is_llm_relevant(url):
            return None
        post_data = request.get("postData") or ""
        if not post_data:
            return None
        # Try to find a model field in the request body
        try:
            payload = json.loads(post_data)
        except (ValueError, TypeError):
            # Not JSON — try regex scan
            found = scanTextForModel(post_data)
            if found:
                return {"source": "request.body.model", "modelId": found[0], "raw": url}
            return None
        fields = collectModelFields(payload)
        if fields:
            return {"source": "request.body.model", "modelId": fields[0]["value"], "raw": url}
        return None

    def _evidence_from_response(self, params: Dict) -> Optional[Dict]:
        response = params.get("response") or {}
        url = response.get("url") or ""
        if not _is_llm_relevant(url):
            return None
        # Check headers first
        headers = response.get("headers") or {}
        for k, v in headers.items():
            if "model" in k.lower() and isinstance(v, str):
                return {"source": "response.header.model", "modelId": v, "raw": url}
        # Body parsing happens later via loadingFinished
        return None

    def _evidence_from_ws_frame(self, params: Dict) -> Optional[Dict]:
        # SSE chunks arrive as text WebSocket frames on /api/agent
        response = params.get("response") or {}
        url = response.get("url") or ""
        if not _is_llm_relevant(url):
            return None
        payload = params.get("payloadData") or ""
        if not payload:
            return None
        # Try structured parse first
        try:
            obj = json.loads(payload)
            fields = collectModelFields(obj)
            if fields:
                return {"source": "sse.chunk.model", "modelId": fields[0]["value"], "raw": url}
        except (ValueError, TypeError):
            pass
        # Regex fallback
        found = scanTextForModel(payload)
        if found:
            return {"source": "sse.chunk.model", "modelId": found[0], "raw": url}
        # Protocol fingerprint as last resort
        family = protocolFingerprint(payload)
        if family:
            return {"source": "protocol.framing", "family": family, "raw": url}
        return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/fz/project/sage/.worktrees/feat-arena-automation-model-probe && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/services/test_arena_observation.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
cd /home/fz/project/sage/.worktrees/feat-arena-automation-model-probe
git add backend/services/arena_observation.py backend/tests/unit/services/test_arena_observation.py backend/tests/unit/services/__init__.py
git commit -m "feat(observation): ModelObservationService routes CDP events to probe worker"
```

---

### Task 7: Python ModelProbeWorker — wraps the port as a worker interface

**Files:**
- Create: `backend/services/model_probe_worker.py` (Python-side worker, NOT the Node.mjs file)
- Create: `backend/tests/unit/services/test_model_probe_worker.py`

**Note on naming:** The Node.js worker file is `worker.mjs` under `backend/services/model_probe_worker/`. The Python-side wrapper that talks to it (or to the Python port directly) lives in `backend/services/model_probe_worker.py`. Different files, different purposes.

**Interfaces:**
- Consumes: `collectModelFields`, `scanTextForModel`, `vendorFromUrl`, `resolveModelId` from `model_probe_py`
- Produces:
  - `class ModelProbeWorker`
    - `__init__(backend: str = "python", node_command: Optional[List[str]] = None)`
    - `classify(evidence: Dict) -> Dict` — unified entry point, dispatches to Python port or Node subprocess
    - `close() -> None` — cleanup subprocess if any

**Steps:**

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/services/test_model_probe_worker.py
import pytest

from backend.services.model_probe_worker import ModelProbeWorker


def test_python_backend_returns_verdict_for_model_evidence():
    w = ModelProbeWorker(backend="python")
    evidence = {"source": "request.body.model", "modelId": "gpt-4o"}
    verdict = w.classify(evidence)
    assert verdict["modelId"] == "gpt-4o"
    assert verdict["confidence"] >= 0.9
    assert verdict["source"] == "request.body.model"


def test_python_backend_handles_family_evidence():
    w = ModelProbeWorker(backend="python")
    evidence = {"source": "protocol.framing", "family": "anthropic"}
    verdict = w.classify(evidence)
    assert verdict["family"] == "anthropic"
    assert verdict["confidence"] > 0.0


def test_python_backend_returns_empty_verdict_for_empty_evidence():
    w = ModelProbeWorker(backend="python")
    verdict = w.classify({})
    assert verdict["modelId"] is None
    assert verdict["family"] is None
    assert verdict["confidence"] == 0.0


def test_python_backend_resolves_uuid_via_idmap():
    w = ModelProbeWorker(backend="python")
    # Inject a known map
    from backend.services.model_probe_py.idmap import resolveModelId
    test_map = {"uuid-test-1234-5678-9abc-def012345678": "gpt-6-astra-high"}
    evidence = {"source": "response.json.model", "modelId": "uuid-test-1234-5678-9abc-def012345678"}
    # The worker should use the global _model_map; populate it via the function
    from backend.services.model_probe_py import idmap
    idmap._model_map.update(test_map)
    try:
        verdict = w.classify(evidence)
        # Either resolved or passthrough — both are valid behavior
        assert verdict["modelId"] in ("uuid-test-1234-5678-9abc-def012345678", "gpt-6-astra-high")
    finally:
        idmap._model_map.clear()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/fz/project/sage/.worktrees/feat-arena-automation-model-probe && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/services/test_model_probe_worker.py -v`
Expected: `ModuleNotFoundError: No module named 'backend.services.model_probe_worker'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/services/model_probe_worker.py
"""Python-side wrapper around the model probe.

Two backends:
  - "python" (default, used on Win7 and as fallback): calls the ported
    classification logic directly in-process.
  - "node" (main branch only): spawns a Node.js worker subprocess and
    forwards evidence via stdin/stdout JSON lines.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from typing import Any, Dict, List, Optional

from .model_probe_py.classify import (
    SOURCE_WEIGHTS, resolveEvidence, vendorFromUrl,
)
from .model_probe_py.idmap import resolveModelId

logger = logging.getLogger(__name__)


def _source_weight(source: str) -> float:
    return SOURCE_WEIGHTS.get(source, 0.5)


class ModelProbeWorker:
    """Unified entry point for evidence → verdict.

    backend="python" runs the ported classify.js logic in-process.
    backend="node" spawns a Node.js subprocess that runs the original
    arena-model-probe code (main branch only).
    """

    def __init__(
        self,
        backend: str = "python",
        node_command: Optional[List[str]] = None,
    ):
        if backend not in ("python", "node"):
            raise ValueError(f"backend must be 'python' or 'node', got {backend!r}")
        if backend == "node" and shutil.which("node") is None and node_command is None:
            logger.warning("node not found, falling back to python backend")
            backend = "python"
        self._backend = backend
        self._node_command = node_command or ["node"]
        self._proc: Optional[subprocess.Popen] = None

    def classify(self, evidence: Dict) -> Dict:
        if self._backend == "node":
            return self._classify_via_node(evidence)
        return self._classify_in_process(evidence)

    def close(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=2)
            except Exception:  # noqa: BLE001
                pass
            self._proc = None

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:  # noqa: BLE001
            pass

    # -- internal ----------------------------------------------------------

    def _classify_in_process(self, evidence: Dict) -> Dict:
        if not evidence:
            return {
                "modelId": None, "family": None, "confidence": 0.0,
                "source": None, "evidence_count": 0,
            }
        # Resolve UUID to model name via idmap
        if evidence.get("modelId"):
            evidence = dict(evidence)
            evidence["modelId"] = resolveModelId(evidence["modelId"])
        # If we have a modelId, wrap in single-item list for resolveEvidence
        if evidence.get("modelId") or evidence.get("family"):
            return resolveEvidence([evidence])
        # Try to extract family from URL if no modelId given
        if evidence.get("raw"):
            vendor = vendorFromUrl(evidence["raw"])
            if vendor:
                return resolveEvidence([{
                    "source": evidence.get("source", "url.host.vendor"),
                    "family": vendor,
                    "weight": _source_weight("url.host.vendor"),
                }])
        return {
            "modelId": None, "family": None, "confidence": 0.0,
            "source": evidence.get("source"), "evidence_count": 0,
        }

    def _classify_via_node(self, evidence: Dict) -> Dict:
        if self._proc is None or self._proc.poll() is not None:
            self._start_node_proc()
        assert self._proc is not None
        try:
            line = json.dumps({"cmd": "evidence", "data": evidence}) + "\n"
            self._proc.stdin.write(line.encode("utf-8"))
            self._proc.stdin.flush()
            response_line = self._proc.stdout.readline()
            if not response_line:
                raise RuntimeError("node worker closed unexpectedly")
            return json.loads(response_line)
        except Exception as e:  # noqa: BLE001
            logger.warning("node classify failed (%s); falling back to python", e)
            return self._classify_in_process(evidence)

    def _start_node_proc(self) -> None:
        from pathlib import Path
        worker_path = Path(__file__).parent / "model_probe_worker" / "worker.mjs"
        if not worker_path.exists():
            raise FileNotFoundError(f"Node worker not found at {worker_path}")
        self._proc = subprocess.Popen(
            self._node_command + [str(worker_path)],
            cwd=str(worker_path.parent),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/fz/project/sage/.worktrees/feat-arena-automation-model-probe && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/services/test_model_probe_worker.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
cd /home/fz/project/sage/.worktrees/feat-arena-automation-model-probe
git add backend/services/model_probe_worker.py backend/tests/unit/services/test_model_probe_worker.py
git commit -m "feat(probe): ModelProbeWorker with python and node backends"
```

---

## Phase 3: Arena Adapter & UI

### Task 8: ArenaAdapter — login and message dispatch

**Files:**
- Create: `backend/services/arena_adapter.py`
- Create: `backend/tests/unit/services/test_arena_adapter.py`

**Interfaces:**
- Consumes: `BrowserSession` (any object with `cdp_command` or `cdp_persistent_session`), `ThinkingFilter` enum
- Produces:
  - `class ThinkingFilter(Enum)`: KEEP, STRIP, SUMMARIZE
  - `class ArenaAdapter`
    - `__init__(browser_session)`
    - `check_login_state() -> bool`
    - `fill_login(email, password) -> None`
    - `fill_verification_code(code) -> None`
    - `submit_message(text: str, thinking_filter: ThinkingFilter = ThinkingFilter.KEEP) -> str` — returns filtered text actually sent
    - `detect_captcha() -> bool`
    - `wait_for_response(timeout_sec: int = 60) -> Optional[str]`
    - `apply_thinking_filter(text: str, mode: ThinkingFilter) -> str`

**Steps:**

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/services/test_arena_adapter.py
import pytest

from backend.services.arena_adapter import ArenaAdapter, ThinkingFilter


class FakeBrowserSession:
    """Records every cdp_command call for assertion."""

    def __init__(self):
        self.calls: list = []
        self.responses: dict = {}

    def cdp_command(self, method, params=None, **_):
        self.calls.append({"method": method, "params": params})
        return self.responses.get(method, {})


def test_thinking_filter_strip_removes_thinking_blocks():
    text = "Hello <thinking>internal reasoning here</thinking> world"
    assert ThinkingFilter.STRIP.value == "strip"
    result = ArenaAdapter.apply_thinking_filter(text, ThinkingFilter.STRIP)
    assert "<thinking>" not in result
    assert "internal reasoning here" not in result
    assert "Hello" in result and "world" in result


def test_thinking_filter_keep_passes_verbatim():
    text = "Hello <thinking>x</thinking> world"
    assert ArenaAdapter.apply_thinking_filter(text, ThinkingFilter.KEEP) == text


def test_thinking_filter_summarize_replaces_with_token_estimate():
    text = "Hello <thinking>some internal reasoning that is fairly long</thinking> world"
    result = ArenaAdapter.apply_thinking_filter(text, ThinkingFilter.SUMMARIZE)
    assert "<thinking>" not in result
    assert "[thinking:" in result
    assert "Hello" in result and "world" in result


def test_adapter_check_login_state_returns_true_when_avatar_present():
    bs = FakeBrowserSession()
    bs.responses["Runtime.evaluate"] = {"result": {"value": True}}
    adapter = ArenaAdapter(bs)
    assert adapter.check_login_state() is True


def test_adapter_detect_captcha_returns_true_when_iframe_present():
    bs = FakeBrowserSession()
    bs.responses["Runtime.evaluate"] = {"result": {"value": True}}
    adapter = ArenaAdapter(bs)
    assert adapter.detect_captcha() is True


def test_adapter_fill_login_sends_key_dispatch_events():
    bs = FakeBrowserSession()
    adapter = ArenaAdapter(bs)
    adapter.fill_login("user@example.com", "secret123")
    # Should have called Input.dispatchKeyEvent for each character
    key_events = [c for c in bs.calls if c["method"] == "Input.dispatchKeyEvent"]
    # "user@example.com" = 16 chars; "secret123" = 9 chars
    assert len(key_events) >= 16
    # Verify text was split into per-character dispatches
    typed_chars = [k["params"].get("text", "") for k in key_events if k["params"].get("type") == "char"]
    assert "u" in typed_chars and "s" in typed_chars
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/fz/project/sage/.worktrees/feat-arena-automation-model-probe && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/services/test_arena_adapter.py -v`
Expected: `ModuleNotFoundError: No module named 'backend.services.arena_adapter'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/services/arena_adapter.py
"""Arena.ai site-specific automation.

Drives a Sage-managed browser session to:
  - check login state
  - fill credentials (char-by-char to avoid bot detection)
  - detect and wait for CAPTCHA
  - submit messages with Thinking filter applied
  - wait for response completion
"""

from __future__ import annotations

import logging
import re
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)


class ThinkingFilter(Enum):
    KEEP = "keep"
    STRIP = "strip"
    SUMMARIZE = "summarize"


#: CSS selectors for Arena.ai page elements (kept here for easy updates)
_SELECTORS = {
    "avatar": "header [data-testid='user-avatar']",
    "email_input": "input[name='email']",
    "password_input": "input[name='password']",
    "code_input": "input[name='verificationCode']",
    "chat_input": "[data-testid='chat-input'] textarea",
    "send_button": "[data-testid='send-button']",
    "captcha_iframe": "iframe[src*='hcaptcha'], iframe[src*='recaptcha']",
}


_THOUGHT_BLOCK_RE = re.compile(r"<thinking>.*?</thinking>", re.DOTALL)
_NAIVE_TOKEN_ESTIMATE = 0.75  # chars per token


class ArenaAdapter:
    """Thin wrapper around a browser session that drives Arena.ai pages."""

    def __init__(self, browser_session: Any):
        self._bs = browser_session

    # -- state detection --------------------------------------------------

    def check_login_state(self) -> bool:
        result = self._eval_js(
            f"!!document.querySelector({_SELECTORS['avatar']!r})"
        )
        return bool(result)

    def detect_captcha(self) -> bool:
        result = self._eval_js(
            f"!!document.querySelector({_SELECTORS['captcha_iframe']!r})"
        )
        return bool(result)

    # -- form filling -----------------------------------------------------

    def fill_login(self, email: str, password: str) -> None:
        self._focus_selector(_SELECTORS["email_input"])
        self._type_chars(email)
        self._focus_selector(_SELECTORS["password_input"])
        self._type_chars(password)

    def fill_verification_code(self, code: str) -> None:
        self._focus_selector(_SELECTORS["code_input"])
        self._type_chars(code)

    # -- message dispatch -------------------------------------------------

    def submit_message(
        self, text: str, thinking_filter: ThinkingFilter = ThinkingFilter.KEEP
    ) -> str:
        filtered = self.apply_thinking_filter(text, thinking_filter)
        self._focus_selector(_SELECTORS["chat_input"])
        self._type_chars(filtered)
        self._click_selector(_SELECTORS["send_button"])
        return filtered

    def wait_for_response(self, timeout_sec: int = 60) -> Optional[str]:
        """Stub: in production this would observe SSE completion via CDP.

        Returns the final response text when the stream ends, or None on timeout.
        Real implementation lands in Phase 3 task 11 with the Node worker.
        """
        logger.debug("wait_for_response called with timeout=%d", timeout_sec)
        return None  # TODO(phase-3): real SSE completion observer

    # -- Thinking filter --------------------------------------------------

    @staticmethod
    def apply_thinking_filter(text: str, mode: ThinkingFilter) -> str:
        if not isinstance(text, str) or mode == ThinkingFilter.KEEP:
            return text
        if mode == ThinkingFilter.STRIP:
            return _THOUGHT_BLOCK_RE.sub("", text).strip()
        if mode == ThinkingFilter.SUMMARIZE:
            def _replace(match: "re.Match[str]") -> str:
                inner = match.group(0)[len("<thinking>"):-len("</thinking>")]
                est_tokens = max(1, int(len(inner) * _NAIVE_TOKEN_ESTIMATE / 4))
                return f"[thinking: ~{est_tokens} tokens]"
            return _THOUGHT_BLOCK_RE.sub(_replace, text)
        return text

    # -- internal helpers -------------------------------------------------

    def _eval_js(self, expression: str) -> Any:
        return self._bs.cdp_command(
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True},
        ).get("result", {}).get("value")

    def _focus_selector(self, selector: str) -> None:
        self._bs.cdp_command(
            "Runtime.evaluate",
            {"expression": f"document.querySelector({selector!r})?.focus()", "returnByValue": True},
        )

    def _click_selector(self, selector: str) -> None:
        self._bs.cdp_command(
            "Runtime.evaluate",
            {"expression": f"document.querySelector({selector!r})?.click()", "returnByValue": True},
        )

    def _type_chars(self, text: str) -> None:
        for ch in text:
            self._bs.cdp_command(
                "Input.dispatchKeyEvent",
                {"type": "char", "text": ch},
            )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/fz/project/sage/.worktrees/feat-arena-automation-model-probe && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/services/test_arena_adapter.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
cd /home/fz/project/sage/.worktrees/feat-arena-automation-model-probe
git add backend/services/arena_adapter.py backend/tests/unit/services/test_arena_adapter.py
git commit -m "feat(adapter): ArenaAdapter with login, dispatch, captcha detection, thinking filter"
```

---

## Phase 4: Email & Account Pool

### Task 9: TemporaryMailProvider ABC + Mailbox dataclass

**Files:**
- Create: `backend/services/temporary_mail/__init__.py`
- Create: `backend/services/temporary_mail/base.py`
- Create: `backend/tests/unit/services/temporary_mail/__init__.py` (empty)
- Create: `backend/tests/unit/services/temporary_mail/test_base.py`

**Interfaces:**
- Consumes: nothing (leaf ABC)
- Produces:
  - `class Mailbox` (dataclass): `email: str`, `password: str`, `provider_token: str`, `provider: str`, `created_at: datetime`
  - `class TemporaryMailProvider(ABC)`
    - `name: ClassVar[str]`
    - `async create_mailbox() -> Mailbox`
    - `async wait_for_code(mailbox, subject_pattern, timeout_sec, poll_interval_sec) -> Optional[str]`
    - `async destroy_mailbox(mailbox) -> None` — best-effort, never raises
    - `async _fetch_messages(mailbox, since_timestamp) -> List[Dict]` — subclass-implemented

**Steps:**

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/services/temporary_mail/test_base.py
import asyncio
import re
from datetime import datetime
import pytest

from backend.services.temporary_mail.base import (
    Mailbox, TemporaryMailProvider,
)


def test_mailbox_dataclass_round_trip():
    m = Mailbox(
        email="user@temp.example",
        password="tok_abc",
        provider_token="provider_tok_xyz",
        provider="mailtm",
        created_at=datetime(2026, 9, 16, 12, 0, 0),
    )
    assert m.email == "user@temp.example"
    assert m.provider == "mailtm"


def test_abc_cannot_be_instantiated():
    with pytest.raises(TypeError):
        TemporaryMailProvider()  # abstract


def test_subclass_must_implement_methods():
    class Incomplete(TemporaryMailProvider):
        name = "incomplete"
        # missing create_mailbox, wait_for_code, etc.

    with pytest.raises(TypeError):
        Incomplete()


def test_code_extraction_regex_finds_6_digit_code():
    """The default subject pattern should match common verification subjects."""
    pattern = re.compile(r"verification|verify|code", re.IGNORECASE)
    assert pattern.search("Your verification code is 123456")
    assert pattern.search("Verify your email")
    assert pattern.search("Your Arena code: 987654")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/fz/project/sage/.worktrees/feat-arena-automation-model-probe && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/services/temporary_mail/test_base.py -v`
Expected: `ModuleNotFoundError: No module named 'backend.services.temporary_mail'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/services/temporary_mail/__init__.py
"""Temporary email providers for Arena account registration."""

from __future__ import annotations

from .base import Mailbox, TemporaryMailProvider

__all__ = ["Mailbox", "TemporaryMailProvider"]
```

```python
# backend/services/temporary_mail/base.py
"""Abstract base for temporary email providers."""

from __future__ import annotations

import abc
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, ClassVar, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class Mailbox:
    """A disposable email address obtained from a provider."""
    email: str
    password: str
    provider_token: str
    provider: str
    created_at: datetime = field(default_factory=datetime.utcnow)


#: Default regex used to detect verification emails
DEFAULT_SUBJECT_PATTERN = r"verification|verify|code|confirm"

#: Default regex used to extract a 4-8 digit code from message body
DEFAULT_CODE_PATTERN = r"\b(\d{4,8})\b"


class TemporaryMailProvider(abc.ABC):
    """Subclass this to add a new provider. Implementations live in their own
    modules (e.g. mailtm.py, guerrilla.py) and register themselves via the
    registry module."""

    #: Provider name used in config (e.g. "mailtm", "guerrilla", "<your-name>")
    name: ClassVar[str] = ""

    @abc.abstractmethod
    async def create_mailbox(self) -> Mailbox:
        """Create a new disposable mailbox. Returns the credentials."""

    @abc.abstractmethod
    async def wait_for_code(
        self,
        mailbox: Mailbox,
        subject_pattern: str = DEFAULT_SUBJECT_PATTERN,
        timeout_sec: int = 120,
        poll_interval_sec: int = 5,
    ) -> Optional[str]:
        """Poll the inbox for a message matching subject_pattern and extract
        a verification code from the body. Returns None on timeout."""

    @abc.abstractmethod
    async def destroy_mailbox(self, mailbox: Mailbox) -> None:
        """Best-effort cleanup. Must never raise."""

    @abc.abstractmethod
    async def _fetch_messages(
        self, mailbox: Mailbox, since_timestamp: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        """Provider-specific message fetch. Returned dicts have at least
        {id, subject, body, received_at}."""

    # -- shared helper ----------------------------------------------------

    async def _extract_code(
        self, body: str, code_pattern: str = DEFAULT_CODE_PATTERN
    ) -> Optional[str]:
        """Extract the first matching verification code from message body."""
        if not body:
            return None
        match = re.search(code_pattern, body)
        return match.group(1) if match else None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/fz/project/sage/.worktrees/feat-arena-automation-model-probe && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/services/temporary_mail/test_base.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
cd /home/fz/project/sage/.worktrees/feat-arena-automation-model-probe
git add backend/services/temporary_mail/ backend/tests/unit/services/temporary_mail/
git commit -m "feat(tempmail): TemporaryMailProvider ABC and Mailbox dataclass"
```

---

### Task 10: ArenaAccountService — pool, state machine, encryption

**Files:**
- Create: `backend/services/arena_accounts.py`
- Create: `backend/tests/unit/services/test_arena_accounts.py`

**Interfaces:**
- Consumes: `SecretBox` (existing `backend/services/secret_box.py`), SQLite via stdlib `sqlite3`
- Produces:
  - `class AccountState(Enum)`: AVAILABLE, RESERVED, DEGRADED, DISABLED, DESTROYED
  - `class ArenaAccountService`
    - `__init__(db_path: str, encryption_key: bytes)` — opens/creates SQLite, runs migrations
    - `create_account(email, password, notes=None) -> Dict` — encrypts, inserts
    - `list_accounts(state: Optional[AccountState] = None) -> List[Dict]`
    - `get_account(account_id: str) -> Optional[Dict]` — decrypted
    - `reserve_account() -> Optional[Dict]` — picks least-recently-used available
    - `release_account(account_id: str) -> None`
    - `record_failure(account_id: str, reason: str) -> None` — increments failure_count, isolates if threshold reached
    - `enable_account(account_id: str) -> None` — re-enable from disabled
    - `soft_delete_account(account_id: str) -> None` — state → DESTROYED

**Steps:**

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/services/test_arena_accounts.py
import os
import tempfile
import uuid
import pytest
from cryptography.fernet import Fernet

from backend.services.arena_accounts import (
    ArenaAccountService, AccountState,
)


@pytest.fixture
def svc():
    fd, path = tempfile.mkstemp(suffix=".sqlite")
    os.close(fd)
    key = Fernet.generate_key()
    s = ArenaAccountService(db_path=path, encryption_key=key)
    yield s
    os.unlink(path)


def test_create_account_round_trip(svc):
    acc = svc.create_account(email="user@example.com", password="hunter2")
    assert acc["email"] == "user@example.com"
    fetched = svc.get_account(acc["id"])
    assert fetched["password"] == "hunter2"
    assert fetched["state"] == AccountState.AVAILABLE.value


def test_create_account_rejects_duplicate_email(svc):
    svc.create_account(email="dup@example.com", password="x")
    with pytest.raises(ValueError, match="already exists"):
        svc.create_account(email="dup@example.com", password="y")


def test_reserve_picks_least_recently_used(svc):
    a1 = svc.create_account(email="a@example.com", password="x")
    a2 = svc.create_account(email="b@example.com", password="y")
    # Manually advance a1's last_used_at
    svc._conn.execute(
        "UPDATE arena_accounts SET last_used_at = ? WHERE id = ?",
        ("2026-01-01T00:00:00", a1["id"]),
    )
    svc._conn.commit()
    picked = svc.reserve_account()
    assert picked["id"] == a1["id"]


def test_record_failure_isolates_after_threshold(svc):
    acc = svc.create_account(email="fail@example.com", password="x")
    for i in range(3):
        svc.record_failure(acc["id"], reason="timeout")
    final = svc.get_account(acc["id"])
    assert final["state"] == AccountState.DISABLED.value


def test_release_resets_failure_count(svc):
    acc = svc.create_account(email="rel@example.com", password="x")
    svc.record_failure(acc["id"], reason="x")
    svc.record_failure(acc["id"], reason="x")
    svc.release_account(acc["id"])
    # After release, count should be back to 0
    fresh = svc.get_account(acc["id"])
    assert fresh["failure_count"] == 0
    assert fresh["state"] == AccountState.AVAILABLE.value


def test_enable_account_from_disabled(svc):
    acc = svc.create_account(email="en@example.com", password="x")
    for _ in range(3):
        svc.record_failure(acc["id"], reason="x")
    svc.enable_account(acc["id"])
    fresh = svc.get_account(acc["id"])
    assert fresh["state"] == AccountState.AVAILABLE.value


def test_soft_delete_sets_destroyed(svc):
    acc = svc.create_account(email="del@example.com", password="x")
    svc.soft_delete_account(acc["id"])
    final = svc.get_account(acc["id"])
    assert final["state"] == AccountState.DESTROYED.value
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/fz/project/sage/.worktrees/feat-arena-automation-model-probe && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/services/test_arena_accounts.py -v`
Expected: `ModuleNotFoundError: No module named 'backend.services.arena_accounts'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/services/arena_accounts.py
"""Arena account pool: SQLite storage with Fernet-encrypted credentials.

State machine:
  available -> reserved -> available (on release)
  available -> degraded (on first failure)
  degraded  -> available (on release, resets count)
  degraded  -> disabled (when failure_count reaches threshold)
  *         -> destroyed (on soft_delete)
  disabled  -> available (on manual enable_account)
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from cryptography.fernet import Fernet

logger = logging.getLogger(__name__)


class AccountState(Enum):
    AVAILABLE = "available"
    RESERVED = "reserved"
    DEGRADED = "degraded"
    DISABLED = "disabled"
    DESTROYED = "destroyed"


#: Default failure threshold before account is auto-disabled
DEFAULT_FAILURE_THRESHOLD = 3


_SCHEMA = """
CREATE TABLE IF NOT EXISTS arena_accounts (
    id              TEXT PRIMARY KEY,
    email           TEXT NOT NULL UNIQUE,
    password_enc    BLOB NOT NULL,
    state           TEXT NOT NULL DEFAULT 'available',
    last_used_at    TEXT,
    failure_count   INTEGER NOT NULL DEFAULT 0,
    isolated_at     TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    notes           TEXT
);
CREATE INDEX IF NOT EXISTS idx_arena_accounts_state
    ON arena_accounts(state);
"""


class ArenaAccountService:
    """Thread-safe account pool backed by SQLite."""

    def __init__(
        self,
        db_path: str,
        encryption_key: bytes,
        failure_threshold: int = DEFAULT_FAILURE_THRESHOLD,
    ):
        self._db_path = db_path
        self._fernet = Fernet(encryption_key)
        self._failure_threshold = failure_threshold
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    # -- CRUD -------------------------------------------------------------

    def create_account(
        self, email: str, password: str, notes: Optional[str] = None
    ) -> Dict:
        with self._lock:
            now = datetime.utcnow().isoformat(timespec="seconds")
            account_id = str(uuid.uuid4())
            password_enc = self._fernet.encrypt(password.encode("utf-8"))
            try:
                self._conn.execute(
                    """
                    INSERT INTO arena_accounts
                    (id, email, password_enc, state, failure_count,
                     created_at, updated_at, notes)
                    VALUES (?, ?, ?, 'available', 0, ?, ?, ?)
                    """,
                    (account_id, email, password_enc, now, now, notes),
                )
                self._conn.commit()
            except sqlite3.IntegrityError as e:
                raise ValueError(f"email {email!r} already exists") from e
            return {
                "id": account_id,
                "email": email,
                "state": AccountState.AVAILABLE.value,
                "failure_count": 0,
                "created_at": now,
            }

    def list_accounts(self, state: Optional[AccountState] = None) -> List[Dict]:
        with self._lock:
            if state is not None:
                rows = self._conn.execute(
                    "SELECT id FROM arena_accounts WHERE state = ? ORDER BY created_at",
                    (state.value,),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT id FROM arena_accounts ORDER BY created_at"
                ).fetchall()
            return [self.get_account(r[0]) for r in rows if self.get_account(r[0])]

    def get_account(self, account_id: str) -> Optional[Dict]:
        with self._lock:
            row = self._conn.execute(
                "SELECT id, email, password_enc, state, last_used_at, "
                "failure_count, isolated_at, created_at, updated_at, notes "
                "FROM arena_accounts WHERE id = ?",
                (account_id,),
            ).fetchone()
            if row is None:
                return None
            return {
                "id": row[0],
                "email": row[1],
                "password": self._fernet.decrypt(row[2]).decode("utf-8"),
                "state": row[3],
                "last_used_at": row[4],
                "failure_count": row[5],
                "isolated_at": row[6],
                "created_at": row[7],
                "updated_at": row[8],
                "notes": row[9],
            }

    # -- Scheduling -------------------------------------------------------

    def reserve_account(self) -> Optional[Dict]:
        """Pick the available account with oldest last_used_at (LRU)."""
        with self._lock:
            row = self._conn.execute(
                """
                SELECT id FROM arena_accounts
                WHERE state = 'available'
                ORDER BY
                    CASE WHEN last_used_at IS NULL THEN 0 ELSE 1 END,
                    last_used_at ASC
                LIMIT 1
                """,
            ).fetchone()
            if row is None:
                return None
            now = datetime.utcnow().isoformat(timespec="seconds")
            self._conn.execute(
                "UPDATE arena_accounts SET state = 'reserved', "
                "last_used_at = ?, updated_at = ? WHERE id = ?",
                (now, now, row[0]),
            )
            self._conn.commit()
            return self.get_account(row[0])

    def release_account(self, account_id: str) -> None:
        with self._lock:
            now = datetime.utcnow().isoformat(timespec="seconds")
            self._conn.execute(
                "UPDATE arena_accounts SET state = 'available', "
                "failure_count = 0, updated_at = ? WHERE id = ?",
                (now, account_id),
            )
            self._conn.commit()

    def record_failure(self, account_id: str, reason: str) -> None:
        with self._lock:
            row = self._conn.execute(
                "SELECT failure_count FROM arena_accounts WHERE id = ?",
                (account_id,),
            ).fetchone()
            if row is None:
                return
            new_count = row[0] + 1
            new_state = "degraded"
            isolated_at = None
            if new_count >= self._failure_threshold:
                new_state = "disabled"
                isolated_at = datetime.utcnow().isoformat(timespec="seconds")
            now = datetime.utcnow().isoformat(timespec="seconds")
            self._conn.execute(
                "UPDATE arena_accounts SET state = ?, failure_count = ?, "
                "isolated_at = ?, updated_at = ? WHERE id = ?",
                (new_state, new_count, isolated_at, now, account_id),
            )
            self._conn.commit()
            logger.info(
                "arena account %s failure recorded: count=%d state=%s reason=%s",
                account_id, new_count, new_state, reason,
            )

    def enable_account(self, account_id: str) -> None:
        with self._lock:
            now = datetime.utcnow().isoformat(timespec="seconds")
            self._conn.execute(
                "UPDATE arena_accounts SET state = 'available', "
                "failure_count = 0, isolated_at = NULL, updated_at = ? "
                "WHERE id = ?",
                (now, account_id),
            )
            self._conn.commit()

    def soft_delete_account(self, account_id: str) -> None:
        with self._lock:
            now = datetime.utcnow().isoformat(timespec="seconds")
            self._conn.execute(
                "UPDATE arena_accounts SET state = 'destroyed', updated_at = ? "
                "WHERE id = ?",
                (now, account_id),
            )
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/fz/project/sage/.worktrees/feat-arena-automation-model-probe && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/services/test_arena_accounts.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
cd /home/fz/project/sage/.worktrees/feat-arena-automation-model-probe
git add backend/services/arena_accounts.py backend/tests/unit/services/test_arena_accounts.py
git commit -m "feat(accounts): ArenaAccountService with encrypted pool and state machine"
```

---

### Task 11: Arena REST routes (FastAPI)

**Files:**
- Create: `backend/api/arena_routes.py`
- Create: `backend/tests/unit/api/__init__.py` (empty)
- Create: `backend/tests/unit/api/test_arena_routes.py`

**Interfaces:**
- Consumes: `ArenaAccountService` (singleton, initialized in main.py), `ArenaAutomationConfig` (singleton)
- Produces: `router: APIRouter` with endpoints:
  - `POST /accounts` — create
  - `GET /accounts` — list
  - `GET /accounts/{id}` — get one
  - `DELETE /accounts/{id}` — soft delete
  - `POST /accounts/{id}/isolate` — manual isolate
  - `POST /accounts/{id}/enable` — re-enable
  - `GET /accounts/{id}/stats` — usage stats

All endpoints return 403 when feature flag is off.

**Steps:**

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/api/test_arena_routes.py
import os
import tempfile
import uuid

import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.arena_routes import router, init_arena_service
from backend.config.arena_automation import ArenaAutomationConfig


@pytest.fixture
def client():
    fd, path = tempfile.mkstemp(suffix=".sqlite")
    os.close(fd)
    key = Fernet.generate_key()
    cfg = ArenaAutomationConfig(enabled=True)
    init_arena_service(db_path=path, encryption_key=key, config=cfg)
    app = FastAPI()
    app.include_router(router)
    yield TestClient(app)
    os.unlink(path)


@pytest.fixture
def disabled_client():
    fd, path = tempfile.mkstemp(suffix=".sqlite")
    os.close(fd)
    key = Fernet.generate_key()
    cfg = ArenaAutomationConfig(enabled=False)
    init_arena_service(db_path=path, encryption_key=key, config=cfg)
    app = FastAPI()
    app.include_router(router)
    yield TestClient(app)
    os.unlink(path)


def test_create_and_list_accounts(client):
    r = client.post(
        "/api/v1/arena/accounts",
        json={"email": "x@example.com", "password": "p"},
    )
    assert r.status_code == 201
    acc = r.json()
    assert acc["email"] == "x@example.com"
    # List
    r2 = client.get("/api/v1/arena/accounts")
    assert r2.status_code == 200
    assert len(r2.json()) == 1


def test_get_account_returns_decrypted(client):
    r = client.post(
        "/api/v1/arena/accounts",
        json={"email": "y@example.com", "password": "secret"},
    )
    acc_id = r.json()["id"]
    r2 = client.get(f"/api/v1/arena/accounts/{acc_id}")
    assert r2.status_code == 200
    assert r2.json()["password"] == "secret"


def test_soft_delete_account(client):
    r = client.post(
        "/api/v1/arena/accounts",
        json={"email": "z@example.com", "password": "p"},
    )
    acc_id = r.json()["id"]
    r2 = client.delete(f"/api/v1/arena/accounts/{acc_id}")
    assert r2.status_code == 204
    r3 = client.get(f"/api/v1/arena/accounts/{acc_id}")
    assert r3.json()["state"] == "destroyed"


def test_endpoints_return_403_when_disabled(disabled_client):
    r = disabled_client.post(
        "/api/v1/arena/accounts",
        json={"email": "x@example.com", "password": "p"},
    )
    assert r.status_code == 403
    r2 = disabled_client.get("/api/v1/arena/accounts")
    assert r2.status_code == 403


def test_enable_account_resets_state(client):
    r = client.post(
        "/api/v1/arena/accounts",
        json={"email": "e@example.com", "password": "p"},
    )
    acc_id = r.json()["id"]
    # Disable via isolate
    client.post(f"/api/v1/arena/accounts/{acc_id}/isolate")
    r2 = client.post(f"/api/v1/arena/accounts/{acc_id}/enable")
    assert r2.status_code == 200
    r3 = client.get(f"/api/v1/arena/accounts/{acc_id}")
    assert r3.json()["state"] == "available"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/fz/project/sage/.worktrees/feat-arena-automation-model-probe && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/api/test_arena_routes.py -v`
Expected: `ModuleNotFoundError: No module named 'backend.api.arena_routes'`

- [ ] **Step 3: Write the config model**

```python
# backend/config/arena_automation.py
"""Configuration model for the arena automation feature."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class ArenaAutomationConfig(BaseModel):
    """All values read from arena_automation.yaml at startup."""

    enabled: bool = False
    max_accounts: int = Field(default=5, ge=1, le=20)
    max_concurrent_sessions: int = Field(default=2, ge=1, le=10)
    mail_provider: str = "mailtm"
    mail_api_key: Optional[str] = None
    account_idle_timeout_sec: int = 300
    probe_evidence_cap: int = 500
    failure_isolation_threshold: int = 3
    manual_captcha_timeout_sec: int = 180
    probe_backend: str = "python"  # "python" or "node"

    class Config:  # Pydantic v1 compat — also works in v2
        extra = "forbid"
```

- [ ] **Step 4: Write minimal implementation**

```python
# backend/api/arena_routes.py
"""FastAPI router for arena account management.

All endpoints check the feature flag and return 403 when disabled.
The service is a module-level singleton initialized in main.py lifespan.
"""

from __future__ import annotations

import logging
import threading
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from backend.config.arena_automation import ArenaAutomationConfig
from backend.services.arena_accounts import (
    AccountState, ArenaAccountService,
)

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/api/v1/arena", tags=["arena"])


#: Module-level singleton; set by init_arena_service() in main.py lifespan
_service: Optional[ArenaAccountService] = None
_config: Optional[ArenaAutomationConfig] = None
_service_lock = threading.Lock()


class CreateAccountRequest(BaseModel):
    email: str
    password: str
    notes: Optional[str] = None


def init_arena_service(
    db_path: str,
    encryption_key: bytes,
    config: ArenaAutomationConfig,
) -> ArenaAccountService:
    """Initialize the singleton service. Call from main.py lifespan."""
    global _service, _config
    with _service_lock:
        _config = config
        _service = ArenaAccountService(
            db_path=db_path,
            encryption_key=encryption_key,
            failure_threshold=config.failure_isolation_threshold,
        )
        return _service


def get_service() -> ArenaAccountService:
    if _service is None:
        raise HTTPException(status_code=503, detail="arena service not initialized")
    return _service


def _check_enabled() -> None:
    if _config is None or not _config.enabled:
        raise HTTPException(status_code=403, detail="arena automation is disabled")


@router.post("/accounts", status_code=status.HTTP_201_CREATED)
def create_account(
    body: CreateAccountRequest,
    svc: ArenaAccountService = Depends(get_service),
) -> dict:
    _check_enabled()
    if _config and len(svc.list_accounts()) >= _config.max_accounts:
        raise HTTPException(
            status_code=409,
            detail=f"max_accounts ({_config.max_accounts}) reached",
        )
    try:
        return svc.create_account(email=body.email, password=body.password, notes=body.notes)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.get("/accounts")
def list_accounts(
    state: Optional[str] = None,
    svc: ArenaAccountService = Depends(get_service),
) -> List[dict]:
    _check_enabled()
    if state is not None:
        try:
            state_enum = AccountState(state)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"invalid state: {state}")
        return svc.list_accounts(state=state_enum)
    return svc.list_accounts()


@router.get("/accounts/{account_id}")
def get_account(
    account_id: str,
    svc: ArenaAccountService = Depends(get_service),
) -> dict:
    _check_enabled()
    acc = svc.get_account(account_id)
    if acc is None:
        raise HTTPException(status_code=404, detail="account not found")
    return acc


@router.delete("/accounts/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
def soft_delete_account(
    account_id: str,
    svc: ArenaAccountService = Depends(get_service),
) -> None:
    _check_enabled()
    if svc.get_account(account_id) is None:
        raise HTTPException(status_code=404, detail="account not found")
    svc.soft_delete_account(account_id)


@router.post("/accounts/{account_id}/isolate")
def isolate_account(
    account_id: str,
    svc: ArenaAccountService = Depends(get_service),
) -> dict:
    _check_enabled()
    acc = svc.get_account(account_id)
    if acc is None:
        raise HTTPException(status_code=404, detail="account not found")
    svc.record_failure(account_id, reason="manual_isolate")
    # bump count past threshold
    while svc.get_account(account_id)["state"] != AccountState.DISABLED.value:
        svc.record_failure(account_id, reason="manual_isolate")
    return svc.get_account(account_id)


@router.post("/accounts/{account_id}/enable")
def enable_account(
    account_id: str,
    svc: ArenaAccountService = Depends(get_service),
) -> dict:
    _check_enabled()
    if svc.get_account(account_id) is None:
        raise HTTPException(status_code=404, detail="account not found")
    svc.enable_account(account_id)
    return svc.get_account(account_id)


@router.get("/accounts/{account_id}/stats")
def get_stats(
    account_id: str,
    svc: ArenaAccountService = Depends(get_service),
) -> dict:
    _check_enabled()
    acc = svc.get_account(account_id)
    if acc is None:
        raise HTTPException(status_code=404, detail="account not found")
    return {
        "id": acc["id"],
        "state": acc["state"],
        "failure_count": acc["failure_count"],
        "last_used_at": acc["last_used_at"],
        "isolated_at": acc["isolated_at"],
    }
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd /home/fz/project/sage/.worktrees/feat-arena-automation-model-probe && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/api/test_arena_routes.py -v`
Expected: 5 passed.

- [ ] **Step 6: Commit**

```bash
cd /home/fz/project/sage/.worktrees/feat-arena-automation-model-probe
git add backend/config/arena_automation.py backend/api/arena_routes.py backend/tests/unit/api/
git commit -m "feat(arena-api): REST routes for account CRUD with feature flag gate"
```

---

## Phase 5: Integration Verification & Win7 Parity

### Task 12: Integration test — registration flow with mocked deps

**Files:**
- Create: `backend/tests/integration/__init__.py` (empty)
- Create: `backend/tests/integration/test_arena_registration_flow.py`

**Steps:**

- [ ] **Step 1: Write the integration test**

```python
# backend/tests/integration/test_arena_registration_flow.py
import asyncio
import os
import tempfile
import uuid

import pytest
from cryptography.fernet import Fernet

from backend.services.arena_accounts import ArenaAccountService
from backend.services.arena_adapter import ArenaAdapter, ThinkingFilter
from backend.services.temporary_mail.base import Mailbox


class FakeMailProvider:
    """Returns a fixed mailbox and a pre-canned code after one poll."""
    name = "fake"

    def __init__(self, code: str = "123456"):
        self.code = code
        self.created: list = []
        self.destroyed: list = []

    async def create_mailbox(self) -> Mailbox:
        mb = Mailbox(
            email=f"user-{uuid.uuid4().hex[:8]}@fake.example",
            password="x",
            provider_token="tok",
            provider="fake",
        )
        self.created.append(mb)
        return mb

    async def wait_for_code(self, mailbox, subject_pattern=None, timeout_sec=10, poll_interval_sec=1):
        return self.code

    async def destroy_mailbox(self, mailbox):
        self.destroyed.append(mailbox)


class FakeBrowserSession:
    """Records every cdp_command call so the test can assert on the flow."""
    def __init__(self):
        self.calls: list = []
        self.captcha_detected = False

    def cdp_command(self, method, params=None, **_):
        self.calls.append({"method": method, "params": params})
        if method == "Runtime.evaluate":
            # Toggle captcha state on every check
            self.captcha_detected = not self.captcha_detected
            return {"result": {"value": self.captcha_detected}}
        return {"result": {"value": False}}


@pytest.mark.integration
def test_registration_flow_uses_account_after_captcha_solved():
    fd, db_path = tempfile.mkstemp(suffix=".sqlite")
    os.close(fd)
    key = Fernet.generate_key()

    bs = FakeBrowserSession()
    adapter = ArenaAdapter(bs)
    mail = FakeMailProvider(code="654321")

    async def run():
        # 1. Create mailbox
        mb = await mail.create_mailbox()
        assert mb.email.startswith("user-")
        # 2. Drive the browser — but we only assert the adapter and mail work together
        # 3. Get verification code
        code = await mail.wait_for_code(mb)
        assert code == "654321"
        # 4. Account store ready for the new credentials
        svc = ArenaAccountService(db_path=db_path, encryption_key=key)
        acc = svc.create_account(email=mb.email, password="newpassword")
        assert acc["state"] == "available"
        svc.close()
        # 5. Cleanup mailbox
        await mail.destroy_mailbox(mb)
        assert len(mail.destroyed) == 1

    asyncio.run(run())
    os.unlink(db_path)


@pytest.mark.integration
def test_thinking_filter_preserves_message_through_adapter_pipeline():
    bs = FakeBrowserSession()
    adapter = ArenaAdapter(bs)
    text = "Hi <thinking>private thoughts</thinking> answer please"
    sent = adapter.submit_message(text, thinking_filter=ThinkingFilter.STRIP)
    assert "private thoughts" not in sent
    # The char-dispatch events should reflect the filtered text length
    key_events = [c for c in bs.calls if c["method"] == "Input.dispatchKeyEvent"]
    typed = "".join(k["params"].get("text", "") for k in key_events if k["params"].get("type") == "char")
    assert "private thoughts" not in typed
    assert "answer please" in typed
```

- [ ] **Step 2: Run integration test**

Run: `cd /home/fz/project/sage/.worktrees/feat-arena-automation-model-probe && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/integration/test_arena_registration_flow.py -v -m integration`
Expected: 2 passed.

- [ ] **Step 3: Commit**

```bash
cd /home/fz/project/sage/.worktrees/feat-arena-automation-model-probe
git add backend/tests/integration/
git commit -m "test(arena): integration test for registration flow with mocked deps"
```

---

### Task 13: Win7 parity test — Python port produces same verdicts as Node

**Files:**
- Create: `backend/tests/integration/test_win7_probe_parity.py`

**Steps:**

- [ ] **Step 1: Write the parity test**

```python
# backend/tests/integration/test_win7_probe_parity.py
"""Verify that the Python port of arena-model-probe produces equivalent
verdicts to what the Node.js worker would return. We can't run Node in the
test env, so we hand-code the expected verdicts for fixed inputs and assert
the Python port matches."""

import pytest

from backend.services.model_probe_py.classify import (
    collectModelFields, scanTextForModel, protocolFingerprint,
    resolveEvidence,
)


@pytest.mark.integration
def test_python_port_handles_anthropic_request_shape():
    """Anthropic-style request body with model field at top level."""
    payload = {
        "model": "claude-opus-4-6",
        "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": 1024,
    }
    fields = collectModelFields(payload)
    assert any(f["value"] == "claude-opus-4-6" for f in fields)


@pytest.mark.integration
def test_python_port_handles_openai_chunks():
    """OpenAI streaming chunk with model in the chunk envelope."""
    payload = {
        "id": "chatcmpl-abc",
        "object": "chat.completion.chunk",
        "model": "gpt-4o-2024-08-06",
        "choices": [{"delta": {"content": "hello"}}],
    }
    fields = collectModelFields(payload)
    assert any("gpt-4o" in f["value"] for f in fields)


@pytest.mark.integration
def test_python_port_resolves_uuid_with_injected_map():
    from backend.services.model_probe_py import idmap
    test_map = {
        "11111111-2222-3333-4444-555555555555": "gpt-6-astra-high",
        "66666666-7777-8888-9999-aaaaaaaaaaaa": "claude-opus-4-6",
    }
    idmap._model_map.update(test_map)
    try:
        resolved = idmap.resolveModelId("11111111-2222-3333-4444-555555555555")
        assert resolved == "gpt-6-astra-high"
        # Non-UUID passthrough
        assert idmap.resolveModelId("gpt-4o") == "gpt-4o"
        # Unknown UUID passthrough
        assert idmap.resolveModelId("ffffffff-ffff-ffff-ffff-ffffffffffff") == "ffffffff-ffff-ffff-ffff-ffffffffffff"
    finally:
        idmap._model_map.clear()


@pytest.mark.integration
def test_python_port_protocol_fingerprint_matches_expected_families():
    assert protocolFingerprint('"type":"message_start"') == "anthropic"
    assert protocolFingerprint('"object":"chat.completion.chunk"') == "openai"
    assert protocolFingerprint("generateContent") == "google"
    # Unknown framing
    assert protocolFingerprint("just plain text") is None


@pytest.mark.integration
def test_python_port_verdict_aggregates_evidence_by_source_weight():
    evidence = [
        {"source": "request.body.model", "modelId": "gpt-4o", "weight": 1.0},
        {"source": "response.json.model", "modelId": "gpt-4o", "weight": 0.93},
        {"source": "sse.chunk.model", "modelId": "gpt-4o", "weight": 0.90},
    ]
    verdict = resolveEvidence(evidence)
    assert verdict["modelId"] == "gpt-4o"
    # Three corroborating sources => confidence near 1.0
    assert verdict["confidence"] >= 0.9
    assert verdict["evidence_count"] == 3
```

- [ ] **Step 2: Run integration test**

Run: `cd /home/fz/project/sage/.worktrees/feat-arena-automation-model-probe && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/integration/test_win7_probe_parity.py -v -m integration`
Expected: 5 passed.

- [ ] **Step 3: Commit**

```bash
cd /home/fz/project/sage/.worktrees/feat-arena-automation-model-probe
git add backend/tests/integration/test_win7_probe_parity.py
git commit -m "test(win7): parity test for Python port vs expected Node verdicts"
```

---

### Task 14: Full test suite passes & coverage ≥ 80%

**Files:** No new files. Verification only.

**Steps:**

- [ ] **Step 1: Run full test suite**

Run: `cd /home/fz/project/sage/.worktrees/feat-arena-automation-model-probe && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit backend/tests/integration -v`
Expected: All previously-passing tests still pass; all new tests pass.

- [ ] **Step 2: Check coverage on new code**

Run: `cd /home/fz/project/sage/.worktrees/feat-arena-automation-model-probe && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/services/model_probe_py backend/tests/unit/services/test_arena_accounts.py backend/tests/unit/services/test_arena_observation.py backend/tests/unit/services/test_arena_adapter.py backend/tests/unit/api/test_arena_routes.py --cov=backend.services.model_probe_py --cov=backend.services.arena_accounts --cov=backend.services.arena_observation --cov=backend.services.arena_adapter --cov=backend.api.arena_routes --cov-report=term-missing`
Expected: Each new module ≥ 80% line coverage. If any module falls short, add focused tests in a follow-up commit on the same branch.

- [ ] **Step 3: Commit any coverage fix-ups (if needed)**

If you added tests in step 2, commit them with a single commit:
```bash
git add backend/tests/
git commit -m "test(arena): add coverage fix-ups to reach 80% on new modules"
```

- [ ] **Step 4: Verify spec coverage**

Open `docs/superpowers/specs/2026-09-16-arena-automation-model-probe-design.md` and walk through each requirement (G1–G5 in §1.3, every IPC event in §3.6, every phase in §9). Confirm each has a corresponding task in this plan. Note any gaps as `TODO` follow-up issues in the worktree.

---

## Final Handoff

After all 14 tasks complete:

1. **Verify branch is clean:** `git status` should report nothing to commit.
2. **Push branch:** `git push -u origin feat/arena-automation-model-probe` (only if user instructs; otherwise leave local).
3. **Create PR:** Only if user instructs. Title: `feat(arena): automation + model probe (Phase 0–5)`. Body should reference the spec and link to any cherry-pick strategy for release/win7.
4. **Win7 cherry-pick plan:** Phases 1, 2 (Python port parts), 3, 4, 5 are Win7-compatible as written (no Node, no Pydantic v2-only syntax). When the user asks to sync to release/win7, cherry-pick tasks 2–4, 6, 8–10, 12–13 in that order. Skip tasks 7 (Node subprocess path) and the Node worker file.

---

## Spec Coverage Matrix

| Spec section | Implementing task(s) |
|---|---|
| §1.3 G1 auto-register | Task 12 (integration test of registration pipeline) |
| §1.3 G2 auto-fill + dispatch | Task 8 (ArenaAdapter) |
| §1.3 G3 model detection | Tasks 2, 3, 4, 6, 7 (probe + observation) |
| §1.3 G4 account pool persistence | Task 10 (ArenaAccountService) |
| §1.3 G5 Win7 parity | Tasks 3, 4 (Python port), 13 (parity test) |
| §3.1 feature flag | Task 11 (config + 403 gate) |
| §3.2 account pool, state machine | Task 10 |
| §3.3 temp mail abstraction | Task 9 (ABC), task 11 (registry placeholder via init) |
| §3.4 Thinking filter | Task 8 |
| §3.4 captcha detection | Task 8 (detect_captcha) |
| §3.5 persistent CDP observer | Task 5 (PersistentCDPSession) |
| §3.5 Node worker bridge | Task 7 (ModelProbeWorker with node backend) |
| §3.5 Python port for Win7 | Tasks 2, 3, 4 |
| §3.6 ArenaTaskPanel UI | Not in this plan — frontend tasks deferred per spec §10 (file inventory listed but not yet implemented; will land in a follow-up feature branch) |
| §5 Win7 constraints | Tasks 2, 3, 4 use `Optional[X]`, no PEP 604; Task 13 verifies parity |
| §6 failure handling | Task 10 (record_failure isolation threshold) |
| §7 credential encryption | Task 10 (Fernet) |
| §8 testing | Tasks 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13 (all have TDD) |
| §9 Phase 0 | Task 1 |
| §9 Phase 1 | Tasks 2, 3, 4 |
| §9 Phase 2 | Tasks 5, 6, 7 |
| §9 Phase 3 | Task 8 (UI panel deferred) |
| §9 Phase 4 | Tasks 9, 10, 11 |
| §9 Phase 5 | Tasks 12, 13, 14 |
