"""Inspired by arena-model-probe/src/classify.js (Python 3.8 compatible).

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
