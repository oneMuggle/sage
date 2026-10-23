# ruff: noqa: UP006, UP007, UP035
"""基于既有 ReviewService 的 harness 离线候选生成（R85）。"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Mapping, Optional, Sequence

from backend.application.kernel.harness_evidence import (
    HarnessProposalError,
    load_harness_evidence,
)
from backend.application.kernel.harness_files import (
    _prepare_root,
    _safe_target,
    _validate_managed_path,
    infer_harness_component,
    verify_harness_files,
)
from backend.application.kernel.harness_proposals import (
    HarnessProposal,
    create_harness_proposal,
)
from backend.domain.message import Message
from backend.skills.review_service import ReviewService, get_review_service

_MAX_TARGET_CHARS = 32 * 1024
_MAX_GOAL_CHARS = 2000
_MAX_EVIDENCE_PROMPT_CHARS = 2000
_TRAJECTORY_KINDS = {"session_event", "message", "tool_trajectory", "llm_replay"}

_PROMPT = """你是 Sage 的 harness 提案工程师。只能输出一个 JSON 对象，不要 Markdown。

目标：{goal}
目标文件：{path}
组件：{component}

只允许完整替换这一个文件；不得提出其他路径。每条 rationale 必须引用给定的 evidence。
必须生成两个候选：
- invariant：修复通用、可复现的缺陷模式；
- domain：利用该文件所属领域流程做最小改进。

输出 schema：
{{
  "title": "提案标题",
  "summary": "为什么需要改、预期行为证据是什么",
  "candidates": [
    {{
      "id": "invariant",
      "lane": "invariant",
      "summary": "候选摘要",
      "content": "完整替换内容",
      "rationale": "证据如何支撑",
      "evidence_ids": ["..."]
    }},
    {{
      "id": "domain",
      "lane": "domain",
      "summary": "候选摘要",
      "content": "完整替换内容",
      "rationale": "证据如何支撑",
      "evidence_ids": ["..."]
    }}
  ]
}}

Evidence：
{evidence}

当前文件完整内容：
--- BEGIN CURRENT FILE ---
{content}
--- END CURRENT FILE ---
"""


class HarnessProposalGenerationError(ValueError):
    """LLM 未产出可锚定的 harness 候选。"""


def _parse_json_object(text: str) -> Dict[str, Any]:
    candidate = text.strip()
    for fence in ("```json", "```"):
        start = candidate.find(fence)
        if start != -1:
            content_start = start + len(fence)
            end = candidate.find("```", content_start)
            if end != -1:
                candidate = candidate[content_start:end].strip()
                break
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise HarnessProposalGenerationError(
            f"failed to parse harness proposal JSON: {exc}"
        ) from exc
    if not isinstance(parsed, dict):
        raise HarnessProposalGenerationError("harness proposal JSON must be an object")
    return parsed


class HarnessProposalService:
    """用 review provider 为单个 harness 文件生成 invariant/domain 候选。"""

    def __init__(
        self,
        review_service: Optional[ReviewService] = None,
        *,
        llm_provider: Any = None,
        model: Optional[str] = None,
    ) -> None:
        if review_service is not None:
            self.review_service = review_service
        elif llm_provider is not None:
            self.review_service = ReviewService(llm_provider, model=model)
        else:
            self.review_service = get_review_service()

    async def generate(
        self,
        root: Any,
        *,
        target_path: str,
        goal: str,
        evidence_ids: Sequence[str],
        title: Optional[str] = None,
        summary: Optional[str] = None,
        author: str = "llm-review",
        proposal_id: Optional[str] = None,
        created_at: Optional[Any] = None,
    ) -> HarnessProposal:
        """生成 draft 提案；不会 Probe、批准或改动托管文件。"""
        if not str(goal or "").strip() or len(str(goal)) > _MAX_GOAL_CHARS:
            raise HarnessProposalGenerationError("proposal goal is required")
        if not evidence_ids:
            raise HarnessProposalGenerationError("proposal generation requires evidence")
        path = _prepare_root(root)
        selected_path = _validate_managed_path(str(target_path))
        component = infer_harness_component(selected_path)
        if component in ("meta", "proposals", "evidence"):
            raise HarnessProposalGenerationError("target is not an editable harness file")
        verification = verify_harness_files(path)
        if not verification.valid or verification.lock is None or selected_path not in verification.lock.by_path:
            raise HarnessProposalGenerationError(
                "proposal generation requires an existing locked harness file"
            )
        try:
            current = _safe_target(path, selected_path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise HarnessProposalGenerationError("target harness file is not UTF-8 text") from exc
        if len(current) > _MAX_TARGET_CHARS:
            raise HarnessProposalGenerationError("target harness file exceeds prompt limit")

        records = []
        allowed_ids: List[str] = []
        for evidence_id in evidence_ids:
            record = load_harness_evidence(path, str(evidence_id))
            records.append(record)
            if record.evidence_id not in allowed_ids:
                allowed_ids.append(record.evidence_id)
        if not any(item.evidence_kind in _TRAJECTORY_KINDS for item in records):
            raise HarnessProposalGenerationError(
                "proposal generation requires trajectory evidence"
            )
        evidence_text = "\n\n".join(
            f"[{item.evidence_id}] kind={item.evidence_kind} source={json.dumps(item.source, ensure_ascii=False, sort_keys=True)}\n{item.excerpt[:_MAX_EVIDENCE_PROMPT_CHARS]}"
            for item in records
        )
        prompt = _PROMPT.format(
            goal=str(goal).strip(),
            path=selected_path,
            component=component,
            evidence=evidence_text,
            content=current,
        )
        provider = self.review_service.llm_provider
        model = getattr(self.review_service, "model", None) or getattr(
            self.review_service, "_model", "sonnet"
        )
        try:
            turn = await provider.complete(
                model=model,
                messages=[
                    Message(role="system", content="你是 harness 提案工程师。请只输出 JSON。"),
                    Message(role="user", content=prompt),
                ],
            )
        except Exception as exc:  # noqa: BLE001 - CLI 需要稳定的生成失败契约
            raise HarnessProposalGenerationError(
                f"LLM provider failed: {type(exc).__name__}: {exc}"
            ) from exc
        text = getattr(turn, "text", None)
        if not text:
            raise HarnessProposalGenerationError("LLM provider returned empty text")
        parsed = _parse_json_object(str(text))
        raw_candidates = parsed.get("candidates")
        if not isinstance(raw_candidates, list) or len(raw_candidates) != 2:
            raise HarnessProposalGenerationError(
                "harness proposal requires invariant and domain candidates"
            )
        record_kinds = {item.evidence_id: item.evidence_kind for item in records}
        candidates: List[Dict[str, Any]] = []
        seen_lanes = set()
        for raw in raw_candidates:
            if not isinstance(raw, Mapping):
                raise HarnessProposalGenerationError("generated candidate must be an object")
            lane = str(raw.get("lane") or raw.get("id") or "")
            if lane not in ("invariant", "domain") or lane in seen_lanes:
                raise HarnessProposalGenerationError(
                    "generated candidates must contain invariant and domain lanes"
                )
            seen_lanes.add(lane)
            content = raw.get("content")
            if not isinstance(content, str) or not content:
                raise HarnessProposalGenerationError("generated candidate content is required")
            if content == current:
                raise HarnessProposalGenerationError("generated candidate is a no-op")
            raw_ids = raw.get("evidence_ids")
            if not isinstance(raw_ids, list) or not raw_ids:
                raise HarnessProposalGenerationError("generated candidate requires evidence")
            cited = [str(item) for item in raw_ids]
            if not set(cited) <= set(allowed_ids):
                raise HarnessProposalGenerationError("generated candidate cites unknown evidence")
            if not any(record_kinds.get(item) in _TRAJECTORY_KINDS for item in cited):
                raise HarnessProposalGenerationError(
                    "generated candidate requires trajectory evidence"
                )
            candidates.append(
                {
                    "id": lane,
                    "lane": lane,
                    "summary": str(raw.get("summary") or ""),
                    "edits": [
                        {
                            "path": selected_path,
                            "operation": "write",
                            "content": content,
                            "evidence_ids": cited,
                            "rationale": str(raw.get("rationale") or ""),
                        }
                    ],
                }
            )
        if seen_lanes != {"invariant", "domain"}:
            raise HarnessProposalGenerationError(
                "generated candidates must contain invariant and domain lanes"
            )
        try:
            return create_harness_proposal(
                path,
                title=str(title or parsed.get("title") or "Harness proposal: " + selected_path),
                summary=str(summary or parsed.get("summary") or ""),
                candidates=candidates,
                author=author,
                proposal_id=proposal_id,
                created_at=created_at,
            )
        except HarnessProposalError as exc:
            raise HarnessProposalGenerationError(str(exc)) from exc


_harness_proposal_service: Optional[HarnessProposalService] = None


def get_harness_proposal_service(
    review_service: Optional[ReviewService] = None,
) -> HarnessProposalService:
    global _harness_proposal_service
    if _harness_proposal_service is None:
        _harness_proposal_service = HarnessProposalService(review_service)
    return _harness_proposal_service


def reset_harness_proposal_service() -> None:
    global _harness_proposal_service
    _harness_proposal_service = None
