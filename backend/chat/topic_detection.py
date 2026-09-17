"""Lightweight topic shift detection.

Two-layer strategy:
1. Regex quick channel — match obvious "change topic" phrases (<1ms).
2. Embedding similarity — compare user input to recent assistant turns;
   if avg cosine similarity < threshold (default 0.35), flag as new topic (<50ms).

Embedding is optional; if embed_fn is None and quick signals miss, returns False.
"""
from __future__ import annotations
import re
from typing import Callable, List, Optional, Sequence, Tuple

QUICK_NEW_TOPIC_SIGNALS = [
    r"换个话题", r"另一个问题", r"新话题", r"不相关的",
    r"另外[，,。]", r"顺便问[一]?下",
    r"new topic", r"unrelated question", r"by the way",
    r"switching to", r"different question",
]

_QUICK_PATTERN = re.compile("|".join(QUICK_NEW_TOPIC_SIGNALS), re.IGNORECASE)
DEFAULT_SIMILARITY_THRESHOLD = 0.35


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def detect_topic_shift(
    user_text: str,
    recent_assistant_texts: List[str],
    embed_fn: Optional[Callable[[str], List[float]]] = None,
    threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
) -> Tuple[bool, str]:
    """Return (is_new_topic, reason).

    reason ∈ {"quick_signal", "embed_similarity", "no_signal"}.
    """
    if _QUICK_PATTERN.search(user_text or ""):
        return True, "quick_signal"

    if embed_fn is None or not recent_assistant_texts:
        return False, "no_signal"

    try:
        user_vec = embed_fn(user_text)
    except Exception:
        return False, "no_signal"

    sims = []
    for txt in recent_assistant_texts[-3:]:
        try:
            sims.append(_cosine(user_vec, embed_fn(txt)))
        except Exception:
            continue
    if not sims:
        return False, "no_signal"

    avg = sum(sims) / len(sims)
    return (avg < threshold, "embed_similarity")
