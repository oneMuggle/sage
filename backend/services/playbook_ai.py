"""LLM-assisted playbook audit: content checks and ambiguous stage adjudication.

The deterministic auditor always runs first. When an LLM is available and the
user requests it, this module asks the model to judge content checks that could
not be decided by keywords, and to adjudicate the stage when evidence is
ambiguous. Failures degrade to the deterministic result.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.services.llm_json import parse_json
from backend.services.playbook_auditor import TEXT_SUFFIXES, audit_playbook

logger = logging.getLogger(__name__)

MAX_FILES_PER_CHECK = 2
MAX_TEXT_CHARS = 6000


@dataclass
class AiAuditResult:
    audit: Dict[str, Any]
    llm_available: bool
    source: str


def _collect_text(root: Path, relative_paths: List[str]) -> str:
    root_resolved = root.resolve()
    parts: List[str] = []
    total = 0
    for relative in relative_paths[:MAX_FILES_PER_CHECK]:
        candidate = (root_resolved / relative).resolve()
        if candidate != root_resolved and root_resolved not in candidate.parents:
            continue
        if not candidate.is_file() or candidate.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            data = candidate.read_bytes()[:MAX_TEXT_CHARS]
            text = data.decode("utf-8", errors="ignore")
        except OSError:
            continue
        if not text.strip():
            continue
        parts.append(f"# {relative}\n{text}")
        total += len(text)
        if total >= MAX_TEXT_CHARS:
            break
    return "\n\n".join(parts)[:MAX_TEXT_CHARS]


async def _judge_check(client: Any, check: Dict[str, Any], text: str) -> Optional[bool]:
    prompt = str(check.get("llm_prompt") or "").strip()
    if not prompt:
        return None
    response = await client.complete(
        f'{prompt}\n\n请只输出 JSON：{{"pass": true|false, "reason": "一句话理由"}}\n\n文档内容：\n{text}'
    )
    payload = parse_json(response)
    if not isinstance(payload, dict):
        return None
    return bool(payload.get("pass"))


async def _adjudicate_stage(client: Any, audit: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    stages = audit.get("stages") or []
    if len(stages) < 2:
        return None
    summary = "\n".join(
        "- %s (%s): 完成度 %d%%，缺失 %s"
        % (
            stage["id"],
            stage["label"],
            stage["progress"],
            ", ".join(item["label"] for item in stage["remaining"]) or "无",
        )
        for stage in stages
    )
    evidence = "; ".join(audit.get("detected_stage", {}).get("evidence") or [])
    response = await client.complete(
        "根据以下项目规程阶段完成度，判断项目最可能处于哪个阶段。"
        '只输出 JSON：{{"stage_id": "阶段 id", "reason": "一句话理由"}}。\n\n'
        f"{summary}\n\n当前记录阶段：{audit.get('current_stage')}\n检测证据：{evidence}"
    )
    payload = parse_json(response)
    if not isinstance(payload, dict):
        return None
    stage_id = str(payload.get("stage_id") or "").strip()
    if stage_id not in {stage["id"] for stage in stages}:
        return None
    return {
        "id": stage_id,
        "confidence": 0.75,
        "evidence": [
            "llm:%s" % (str(payload.get("reason") or "")[:300] or "模型裁决")
        ],
        "source": "llm",
    }


async def audit_with_llm(
    project: Any,
    spec: Dict[str, Any],
    *,
    state: Optional[Dict[str, Any]] = None,
    use_llm: bool = True,
    llm_client: Any = None,
) -> AiAuditResult:
    """Run the deterministic audit, then optionally refine it with an LLM."""
    audit = audit_playbook(project, spec, state=state)
    client = llm_client
    if client is None and use_llm:
        try:
            from backend.orchestration.llm_factory import build_llm_client_from_settings

            client = build_llm_client_from_settings()
        except Exception:  # noqa: BLE001 — LLM is optional
            logger.warning("failed to build LLM client for playbook audit", exc_info=True)
            client = None

    if client is None:
        return AiAuditResult(audit=audit, llm_available=False, source="deterministic")

    root = Path(getattr(project, "path", ""))
    changed = False
    try:
        for stage in audit.get("stages") or []:
            for artifact in stage.get("artifacts") or []:
                if artifact.get("status") not in {"present", "stale"}:
                    continue
                text = _collect_text(root, artifact.get("evidence", {}).get("matches") or [])
                if not text:
                    continue
                for check in artifact.get("checks") or []:
                    if check.get("type") not in {"llm", "keyword_or_llm"}:
                        continue
                    if check.get("status") == "pass":
                        continue
                    passed = await _judge_check(client, check, text)
                    if passed is None:
                        continue
                    check["status"] = "pass" if passed else "fail"
                    check["source"] = "llm"
                    changed = True
    except Exception:  # noqa: BLE001 — LLM failures must not break the audit
        logger.warning("LLM content check failed, keeping deterministic result", exc_info=True)

    detected = audit.get("detected_stage") or {}
    if (detected.get("confidence") or 0) < 0.6:
        try:
            adjudicated = await _adjudicate_stage(client, audit)
            if adjudicated is not None:
                audit["detected_stage"] = adjudicated
                changed = True
        except Exception:  # noqa: BLE001 — adjudication is best-effort
            logger.warning("LLM stage adjudication failed", exc_info=True)

    return AiAuditResult(
        audit=audit,
        llm_available=changed,
        source="llm" if changed else "deterministic",
    )


__all__ = ["AiAuditResult", "audit_with_llm"]
