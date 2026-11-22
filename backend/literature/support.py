"""语义 claim support 摄入（Layer 3b）。

LLM 在 skill 中阅读 `claims.jsonl` 与 `evidence.jsonl`，输出 judgments JSON：

```json
[
  {"claim_id": "c0001", "support": "supported",
   "rationale": "证据 e1 的发现直接支持该句", "evidence_refs": ["e1"]}
]
```

`support` 取值：`supported` / `flagged` / `unsupported` / `unclear`。
本模块只做确定性校验与合并；语义判断由 LLM 完成。
"""

from __future__ import annotations

from typing import Any, Dict, List, Sequence

from .pipeline_models import Claim, ClaimVerdict

VALID_SUPPORT = frozenset(
    {
        ClaimVerdict.SUPPORTED,
        ClaimVerdict.FLAGGED,
        ClaimVerdict.UNSUPPORTED,
        ClaimVerdict.UNCLEAR,
    }
)


def _judgment_notes(judgment: Dict[str, Any]) -> str:
    rationale = str(judgment.get("rationale") or "").strip()
    refs = judgment.get("evidence_refs") or []
    ref_text = ", ".join(str(ref) for ref in refs if str(ref).strip())
    parts = []
    if rationale:
        parts.append(rationale)
    if ref_text:
        parts.append(f"证据: {ref_text}")
    return "；".join(parts)


def apply_claim_support(
    claims: Sequence[Claim],
    judgments: Sequence[Dict[str, Any]],
) -> List[Claim]:
    """把 LLM 的 claim-support 判定合并进 claims。

    - 未知 claim_id / 非法 support → ValueError；
    - `unresolved` / `unsupported` 的 claim 保持原状（存在性问题优先）；
    - 其余 claim 用 judgment 的 support 覆盖 verdict，并追加 rationale/证据引用。
    """
    by_id: Dict[str, Dict[str, Any]] = {}
    for judgment in judgments:
        if not isinstance(judgment, dict):
            raise ValueError("claim judgment 必须是对象")
        claim_id = str(judgment.get("claim_id") or "").strip()
        if not claim_id:
            raise ValueError("claim judgment 缺少 claim_id")
        support = str(judgment.get("support") or "").strip().lower()
        if support not in VALID_SUPPORT:
            raise ValueError(
                f"claim {claim_id} 的 support 必须是 {sorted(VALID_SUPPORT)} 之一"
            )
        if claim_id in by_id:
            raise ValueError(f"claim_id 重复: {claim_id}")
        by_id[claim_id] = judgment

    known_ids = {claim.claim_id for claim in claims}
    unknown = sorted(set(by_id) - known_ids)
    if unknown:
        raise ValueError(f"judgment 引用了未知 claim_id: {', '.join(unknown)}")

    result: List[Claim] = []
    for claim in claims:
        judgment = by_id.get(claim.claim_id)
        if judgment is None or claim.verdict in (
            ClaimVerdict.UNRESOLVED,
            ClaimVerdict.UNSUPPORTED,
        ):
            result.append(claim)
            continue
        extra_notes = _judgment_notes(judgment)
        notes = "；".join(part for part in (claim.notes, extra_notes) if part)
        result.append(
            Claim(
                claim_id=claim.claim_id,
                section=claim.section,
                text=claim.text,
                citation_keys=claim.citation_keys,
                verdict=judgment["support"],
                notes=notes,
                metadata_schema_ok=claim.metadata_schema_ok,
            )
        )
    return result


def summarize_claim_support(claims: Sequence[Claim]) -> Dict[str, int]:
    summary: Dict[str, int] = {}
    for claim in claims:
        summary[claim.verdict] = summary.get(claim.verdict, 0) + 1
    return summary


__all__ = [
    "VALID_SUPPORT",
    "apply_claim_support",
    "summarize_claim_support",
]
