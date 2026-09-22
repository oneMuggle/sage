"""Pure parsing helpers for arena draw traces (plan §5.5, arena_trace_ext).

Everything here is a pure function over dicts/JSON text — no HTTP, no clock.
Official model + provider extraction reuses ``run_trace_resolver`` (plan
appendix C #1: don't reimplement what already has unit tests); this module
adds the pieces the reference draw engine needed on top:

* internal config names (``"modelName"`` JSON field scanned over raw events),
* tier suffixes (``gpt-6-astra-low`` → base + tier),
* usage numbers from span details (usage spans carry top-level fields,
  stream spans carry dotted paths — usage wins, stream is weak fallback),
* keep-pattern matching (invalid regex degrades to escaped literal, matching
  the reference's forgiving behaviour).

Field maps ported from reference/ArenCard/arena_draw.py:260-283 verbatim
(protocol constants, not creative code — see
docs/technical/50-arena-source-license-audit.md).
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Tuple

from backend.services.run_trace_resolver import extract_models_from_trace

#: event message -> span kind
SPAN_KINDS = {
    "ai.streamText.doStream": "stream",
    "token.usage.recorded": "usage",
    "spend.recorded": "cost",
}

#: usage spans carry these as **top-level** properties fields
USAGE_TOP = (
    "modelName",
    "provider",
    "usageSource",
    "inputTokens",
    "outputTokens",
    "totalTokens",
    "reasoningTokens",
    "cacheReadTokens",
    "cacheWriteTokens",
)

#: stream spans carry these under dotted paths (weak evidence)
STREAM_KEYS = (
    ("reasoningTokens", "ai.usage.reasoningTokens"),
    ("inputTokens", "ai.usage.inputTokens"),
    ("outputTokens", "ai.usage.outputTokens"),
    ("totalTokens", "ai.usage.totalTokens"),
    ("requestModel", "gen_ai.request.model"),
    ("responseModel", "gen_ai.response.model"),
)

#: reasoning-effort settings the reference probed for; never observed in the
#: wild (only openai.serviceTier) — kept so absence stays documented.
SETTING_HINTS = (
    "ai.settings.providerOptions",
    "ai.prompt.providerOptions",
    "ai.response.providerMetadata",
    "ai.settings.reasoningEffort",
    "ai.settings.thinking",
    "gen_ai.request.reasoning_effort",
)

#: internal config name inside raw event JSON (reference MODEL_NAME_RE)
MODEL_NAME_RE = re.compile(r'"modelName"\s*:\s*"([^"]{2,80})"')

#: tier suffix in internal config names (reference _TIER_RE)
TIER_RE = re.compile(
    r"^(?P<base>.+?)[.-](?P<tier>low|medium|high|max)(?:[.-](?P<date>\d{6,8}))?$",
    re.I,
)


def _dig(obj: Any, path: str) -> Any:
    cur = obj
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def extract_internal_names(events: Dict[str, Any]) -> List[str]:
    """All internal config names appearing anywhere in the run events JSON.

    The internal name (e.g. ``gpt-6-astra-low``) is not part of the styled
    event objects — the reference scans the serialized JSON for
    ``"modelName"`` fields. Sorted + deduplicated for deterministic output.
    """
    try:
        raw = json.dumps(events or {}, ensure_ascii=False)
    except (TypeError, ValueError):
        return []
    return sorted(set(MODEL_NAME_RE.findall(raw)))


def parse_tier(name: str) -> Tuple[str, str]:
    """Split an internal config name into (base, tier).

    ``gpt-6-astra-low`` → ``("gpt-6-astra", "low")``; no tier suffix →
    ``("", "")``. Note (reference comment): the tier is Arena's own config
    label, not a vendor-confirmed reasoning strength.
    """
    match = TIER_RE.match(str(name or "").strip())
    if not match:
        return "", ""
    return match.group("base").strip(), match.group("tier").lower()


def model_matches(model: str, internal: str, pattern: str) -> bool:
    """Empty pattern keeps everything; otherwise official OR internal name hit.

    An invalid regex degrades to an escaped literal match instead of raising
    (user-supplied patterns must never crash a draw round).
    """
    p = str(pattern or "").strip()
    if not p:
        return True
    try:
        rx = re.compile(p, re.I)
    except re.error:
        rx = re.compile(re.escape(p), re.I)
    return bool(rx.search(model or "") or rx.search(internal or ""))


def extract_usage(span_detail: Dict[str, Any], kind: str) -> Dict[str, Any]:
    """Extract usage fields from ONE span detail.

    ``kind`` comes from SPAN_KINDS: "usage" reads top-level fields
    (authoritative), "stream" reads dotted paths (weak). Numbers become int,
    strings are kept as-is; missing fields are omitted.
    """
    props = span_detail.get("properties") if isinstance(span_detail, dict) else None
    if not isinstance(props, dict):
        return {}
    out: Dict[str, Any] = {}
    if kind == "usage":
        for key in USAGE_TOP:
            value = props.get(key)
            if isinstance(value, bool):
                continue
            if isinstance(value, (int, float)):
                out[key] = int(value)
            elif isinstance(value, str) and key not in out:
                out[key] = value
    elif kind == "stream":
        for name, path in STREAM_KEYS:
            value = _dig(props, path)
            if isinstance(value, bool):
                continue
            if isinstance(value, (int, float)):
                out[name] = int(value)
            elif isinstance(value, str) and name not in out:
                out[name] = value
    return out


def setting_hints(span_detail: Dict[str, Any]) -> List[str]:
    """Which reasoning-effort probe paths actually exist in this span."""
    props = span_detail.get("properties") if isinstance(span_detail, dict) else None
    if not isinstance(props, dict):
        return []
    return [h for h in SETTING_HINTS if _dig(props, h) is not None]


def span_ids(events: Dict[str, Any], kinds=None, max_n: int = 0) -> List[str]:
    """Ids of span-bearing events, newest last (usage reading order).

    ``kinds`` filters by SPAN_KINDS value (e.g. ("usage", "stream")).
    ``max_n`` > 0 keeps only the last ``max_n`` entries.
    """
    wanted = set(kinds) if kinds else set(SPAN_KINDS.values())
    ids: List[str] = []
    for event in (events or {}).get("events") or []:
        if not isinstance(event, dict):
            continue
        kind = SPAN_KINDS.get(str(event.get("message")))
        if kind not in wanted:
            continue
        span_id = str(event.get("spanId") or "")
        if span_id:
            ids.append(span_id)
    if max_n and max_n > 0:
        ids = ids[-max_n:]
    return ids


def parse_models(events: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Official model list with internal name attached (reference parse_models).

    Returns ``[{"model", "provider", "internal", "tokens", "cost_usd"}]``.
    Official names come from ``run_trace_resolver.extract_models_from_trace``
    (already unit-tested there); the first internal name found in the raw JSON
    is attached to the first entry — the reference observed exactly one model
    per draw round, so index-0 attachment preserves its behaviour.
    """
    entries = _models_without_run_filter(events)
    if not entries:
        return []
    internal = extract_internal_names(events)
    if internal:
        entries[0]["internal"] = internal[0]
    return entries


def _models_without_run_filter(events: Dict[str, Any]) -> List[Dict[str, Any]]:
    """extract_models_from_trace with runId matching relaxed.

    The resolver skips events whose runId != given id; a draw round fetched
    events *for* its run, so every event already belongs to it. Feed the
    resolver each event's own runId to reuse its styling extraction verbatim.
    """
    seen: List[Dict[str, Any]] = []
    for event in (events or {}).get("events") or []:
        if not isinstance(event, dict):
            continue
        run_id = str(event.get("runId") or "")
        for entry in extract_models_from_trace({"events": [event]}, run_id):
            if entry not in seen:
                seen.append(entry)
    return seen
