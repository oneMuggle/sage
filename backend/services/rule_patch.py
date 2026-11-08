"""AI 辅助规则修改：上下文组装、schema 校验、diff 预览（无状态）。

本模块只做纯计算与 LLM 调用，**不写库**；落库在
``backend/api/project_rules_routes.apply_rule_patch`` 里复用写原语，避免 service
反向依赖 API 层。patch 不落库：preview 与 apply 各自重新读取当前规则。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from backend.services.llm_json import parse_json
from backend.services.markdown_rules import MAX_RULE_CHARS

logger = logging.getLogger(__name__)

MAX_CONTEXT_CHARS = 6000
MAX_CONTENT_CHARS_IN_CONTEXT = 300
MAX_PATCH_OPERATIONS = 30
WRITABLE_LAYERS = ("constraint", "doc", "global")
PATCH_ACTIONS = ("add", "update", "delete", "toggle")
LLM_UNAVAILABLE_MESSAGE = "AI 暂不可用，可手动编辑"
SCHEMA_FINAL_MESSAGE = "AI 返回格式不正确，请重试或手动编辑"


class PatchSchemaError(ValueError):
    """LLM 输出在两次尝试后仍不符合 patch schema。"""


@dataclass
class PatchOperation:
    op_id: str
    action: str
    layer: str
    rule_id: Optional[str] = None
    before: Dict[str, Any] = field(default_factory=dict)
    after: Dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    expected_updated_at: Optional[int] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "op_id": self.op_id,
            "action": self.action,
            "layer": self.layer,
            "rule_id": self.rule_id,
            "before": self.before,
            "after": self.after,
            "reason": self.reason,
            "expected_updated_at": self.expected_updated_at,
            "error": self.error,
        }


_CAPTURE_FIELDS = (
    "id",
    "layer",
    "category",
    "content",
    "enabled",
    "priority",
    "trigger",
    "updated_at",
)


def _snapshot(entry: Any) -> Dict[str, Any]:
    return {name: getattr(entry, name, None) for name in _CAPTURE_FIELDS}


def build_rules_context(
    entries: Sequence[Any], *, limit: int = MAX_CONTEXT_CHARS
) -> str:
    """把四层规则压成有界文本；超长条目截断，超出总预算就停。"""
    lines: List[str] = []
    used = 0
    for entry in entries:
        content = str(getattr(entry, "content", "") or "").strip().replace("\n", " ")
        if len(content) > MAX_CONTENT_CHARS_IN_CONTEXT:
            content = content[:MAX_CONTENT_CHARS_IN_CONTEXT] + "…"
        line = "[{layer}] {source} | {category} | {state} | id={rule_id}\n  {content}\n".format(
            layer=getattr(entry, "layer", ""),
            source=getattr(entry, "source_label", ""),
            category=getattr(entry, "category", ""),
            state="启用" if getattr(entry, "enabled", True) else "停用",
            rule_id=getattr(entry, "id", ""),
            content=content,
        )
        if used + len(line) > limit:
            break
        lines.append(line)
        used += len(line)
    return "".join(lines) or "（当前没有规则）"


_PATCH_INSTRUCTIONS = """你是 Sage 项目工作台的规则助手。根据用户指令提出规则修改。

要求：
- 可写层只有三层：constraint（项目规则，可增删改停用）、doc（项目根 SAGE.md 的小节）、global（全局规则 ~/.sage/SAGE.md 的小节）。
- playbook（规程）层只读：仍可输出 operation，但会被标记为只读建议，不能应用。
- update / delete / toggle 必须填当前列表里的 rule_id；update 项目规则还要填 expected_updated_at，update Markdown 层要填 before.content。
- add 时 rule_id 为 null，after 里给 category 与 content。
- 单条 content 不超过 {max_chars} 字。
- 只输出 JSON，不要任何解释。格式：
{{"operations": [{{"op_id": "op-1", "action": "add|update|delete|toggle", "layer": "constraint|doc|global|playbook", "rule_id": null, "before": {{}}, "after": {{"category": "测试", "content": "跑 pytest", "trigger_pattern": null, "priority": 5, "enabled": true}}, "reason": "一句话理由", "expected_updated_at": null}}]}}"""


def build_patch_prompt(
    project_name: str, project_type: str, instruction: str, context: str
) -> str:
    header = (
        f"项目：{project_name}（{project_type}）\n\n"
        f"当前规则：\n{context}\n\n"
        f"用户指令：{instruction}\n\n"
    )
    return header + _PATCH_INSTRUCTIONS.format(max_chars=MAX_RULE_CHARS)


def _as_int(value: Any) -> Optional[int]:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_operation(raw: Any, index: int) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        raise PatchSchemaError("operations 里出现了非对象项")
    action = str(raw.get("action") or "").strip()
    layer = str(raw.get("layer") or "").strip()
    if action not in PATCH_ACTIONS:
        raise PatchSchemaError("未知操作类型：{}".format(action or "空"))
    if layer not in WRITABLE_LAYERS + ("playbook",):
        raise PatchSchemaError("未知规则层：{}".format(layer or "空"))
    after = raw.get("after") if isinstance(raw.get("after"), dict) else {}
    before = raw.get("before") if isinstance(raw.get("before"), dict) else {}
    rule_id = raw.get("rule_id")
    return {
        "op_id": str(raw.get("op_id") or f"op-{index + 1}"),
        "action": action,
        "layer": layer,
        "rule_id": str(rule_id) if rule_id else None,
        "before": before,
        "after": after,
        "reason": str(raw.get("reason") or "")[:300],
        "expected_updated_at": _as_int(raw.get("expected_updated_at")),
    }


def parse_patch_response(raw: str) -> List[Dict[str, Any]]:
    """解析 LLM 输出；任何结构问题都归一成 ``PatchSchemaError``。"""
    try:
        payload = parse_json(raw)
    except ValueError as exc:
        raise PatchSchemaError("AI 返回的不是 JSON 对象") from exc
    operations = payload.get("operations")
    if not isinstance(operations, list):
        raise PatchSchemaError("缺少 operations 数组")
    if len(operations) > MAX_PATCH_OPERATIONS:
        raise PatchSchemaError(f"一次最多提出 {MAX_PATCH_OPERATIONS} 条修改")
    return [_coerce_operation(item, index) for index, item in enumerate(operations)]


def _operation_from_raw(raw: Dict[str, Any]) -> PatchOperation:
    return PatchOperation(
        op_id=raw["op_id"],
        action=raw["action"],
        layer=raw["layer"],
        rule_id=raw.get("rule_id"),
        before=dict(raw.get("before") or {}),
        after=dict(raw.get("after") or {}),
        reason=raw.get("reason") or "",
        expected_updated_at=raw.get("expected_updated_at"),
    )


def _add_content_error(after: Dict[str, Any]) -> Optional[str]:
    content = str(after.get("content") or "").strip()
    if not content:
        return "empty_content"
    if len(content) > MAX_RULE_CHARS:
        return "content_too_long"
    return None


def _enrich_existing(operation: PatchOperation, entry: Any) -> None:
    """补 before 快照与 expected_updated_at，并校验 update/toggle 载荷。"""
    operation.before = _snapshot(entry)
    if operation.layer == "constraint" and operation.expected_updated_at is None:
        operation.expected_updated_at = getattr(entry, "updated_at", None)
    if operation.action == "toggle" and not isinstance(
        operation.after.get("enabled"), bool
    ):
        operation.error = "invalid_patch"
    if operation.action == "update":
        content = str(operation.after.get("content") or "").strip()
        if len(content) > MAX_RULE_CHARS:
            operation.error = "content_too_long"
        elif operation.layer != "constraint" and not content:
            operation.error = "empty_content"


def enrich_operations(
    raw_ops: List[Dict[str, Any]], entries: Sequence[Any]
) -> List[PatchOperation]:
    """补当前值、提前标出不可执行项；apply 会再校验一遍。"""
    by_id = {getattr(entry, "id", ""): entry for entry in entries}
    enriched: List[PatchOperation] = []
    for raw in raw_ops:
        operation = _operation_from_raw(raw)
        if operation.layer == "playbook":
            operation.error = "readonly_layer"
            enriched.append(operation)
            continue
        if operation.action == "add":
            operation.before = {}
            error = _add_content_error(operation.after)
            if error:
                operation.error = error
            enriched.append(operation)
            continue
        entry = by_id.get(operation.rule_id or "")
        if entry is None:
            operation.error = "rule_not_found"
            enriched.append(operation)
            continue
        if getattr(entry, "editable", "readonly") != "full":
            operation.error = "readonly_layer"
            enriched.append(operation)
            continue
        _enrich_existing(operation, entry)
        enriched.append(operation)
    return enriched


def _build_client() -> Any:
    try:
        from backend.orchestration.llm_factory import build_llm_client_from_settings

        return build_llm_client_from_settings()
    except Exception:  # noqa: BLE001 — LLM 是可选能力
        logger.warning("failed to build LLM client for rule patch", exc_info=True)
        return None


async def preview_patch(
    project: Any,
    instruction: str,
    entries: Sequence[Any],
    *,
    focus_rule_id: Optional[str] = None,
    llm_client: Any = None,
) -> Dict[str, Any]:
    client = llm_client if llm_client is not None else _build_client()
    if client is None:
        return {"llm_available": False, "message": LLM_UNAVAILABLE_MESSAGE, "operations": []}
    scoped: Sequence[Any] = entries
    if focus_rule_id:
        focused = [entry for entry in entries if getattr(entry, "id", "") == focus_rule_id]
        scoped = focused or entries
    prompt = build_patch_prompt(
        str(getattr(project, "name", "") or ""),
        str(getattr(project, "project_type", "") or ""),
        instruction,
        build_rules_context(scoped),
    )
    repair_prompt = prompt
    for attempt in range(2):
        try:
            response = await client.complete(prompt if attempt == 0 else repair_prompt)
        except Exception:  # noqa: BLE001 — LLM 调用失败要给出明确提示而非 500
            logger.warning("AI rule patch call failed", exc_info=True)
            return {"llm_available": False, "message": LLM_UNAVAILABLE_MESSAGE, "operations": []}
        try:
            raw_ops = parse_patch_response(response)
        except PatchSchemaError as exc:
            repair_prompt = prompt + f"\n\n上一次输出无法解析（{exc}）。请只输出符合要求的 JSON。"
            continue
        operations = enrich_operations(raw_ops, entries)
        return {
            "llm_available": True,
            "message": "",
            "operations": [operation.to_dict() for operation in operations],
        }
    raise PatchSchemaError(SCHEMA_FINAL_MESSAGE)


__all__ = [
    "LLM_UNAVAILABLE_MESSAGE",
    "MAX_CONTEXT_CHARS",
    "MAX_CONTENT_CHARS_IN_CONTEXT",
    "MAX_PATCH_OPERATIONS",
    "PatchOperation",
    "PatchSchemaError",
    "SCHEMA_FINAL_MESSAGE",
    "build_patch_prompt",
    "build_rules_context",
    "enrich_operations",
    "parse_patch_response",
    "preview_patch",
]
