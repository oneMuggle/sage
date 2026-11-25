"""LLM-assisted refinement of extracted rule drafts.

The user speaks in natural language ("加上参考文献格式要求", "行间距改成1.5倍"),
the LLM proposes structured actions (add/modify/delete/explain), and every
action is re-validated deterministically before it reaches the UI. The user
still accepts or rejects each action — nothing is applied automatically.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

MAX_RULES = 100
MAX_INSTRUCTION_CHARS = 2000
MAX_ACTIONS = 20

_ALLOWED_PATCH_KEYS = (
    "name",
    "params",
    "severity",
    "description",
    "ai_prompt",
    "type",
    "scope",
)
_ALLOWED_SEVERITIES = ("error", "warning", "info")
_ALLOWED_TYPES = ("format", "terminology", "citation", "structure", "custom")
_ALLOWED_SCOPES = ("full", "heading", "body", "table", "caption")

_REFINE_PROMPT = """你是 Word 文档格式规则的编辑助手。下面是当前的规则草稿（JSON 数组），
每条包含 temp_id、name、kind、params、severity、description、ai_prompt、type、scope。

用户会用自然语言要求你增删改规则。请输出一个 JSON 数组，每个元素是以下四种之一：
1. 新增规则：{{"type":"add","rule":{{"name":"规则名","kind":"style.font","params":{{}},"severity":"warning","description":"说明","ai_prompt":"给审计 AI 的检查指令","type":"format","scope":"body"}},"explanation":"为什么这样加"}}
2. 修改规则：{{"type":"modify","temp_id":"草稿中的 id","patch":{{"name"?:string,"params"?:object,"severity"?:"error"|"warning"|"info","description"?:string,"ai_prompt"?:string,"type"?:string,"scope"?:string}},"explanation":"改了什么"}}
3. 删除规则：{{"type":"delete","temp_id":"草稿中的 id","explanation":"为什么删"}}
4. 仅解释（不改规则）：{{"type":"explain","explanation":"回答用户问题"}}

规则：
1. 只修改用户明确要求的部分；未提及的规则一律不动。
2. modify/delete 的 temp_id 必须来自下方规则列表。
3. params 中的数值不确定时保留原值，不要编造。
4. 如果用户只是提问，输出 explain 回答，不要增删改。
5. 只输出 JSON 数组，不要 markdown 围栏或额外解释。

当前规则（JSON）：
{rules}

用户指令：
{instruction}
"""


class RefineError(ValueError):
    """Raised when the LLM response cannot be turned into valid actions."""


def parse_refine_payload(text: str) -> List[Any]:
    """Parse a JSON array, tolerating markdown fences and surrounding prose."""
    raw = (text or "").strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"\s*```$", "", raw)
    start = raw.find("[")
    end = raw.rfind("]")
    if start == -1 or end == -1 or end < start:
        raise RefineError("响应中没有 JSON 数组")
    data = json.loads(raw[start : end + 1])
    if not isinstance(data, list):
        raise RefineError("响应不是 JSON 数组")
    return data


def _clean_text(value: Any, max_len: int) -> Optional[str]:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned[:max_len] if cleaned else None


def _validate_add(raw: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(raw, dict):
        return None
    name = _clean_text(raw.get("name"), 200)
    if not name:
        return None
    return {
        "name": name,
        "kind": _clean_text(raw.get("kind"), 80) or "custom",
        "params": raw.get("params") if isinstance(raw.get("params"), dict) else {},
        "severity": raw.get("severity")
        if raw.get("severity") in _ALLOWED_SEVERITIES
        else "warning",
        "description": _clean_text(raw.get("description"), 1000) or "",
        "ai_prompt": _clean_text(raw.get("ai_prompt"), 1000)
        or f"检查文档是否满足规则「{name}」",
        "type": raw.get("type") if raw.get("type") in _ALLOWED_TYPES else "custom",
        "scope": raw.get("scope") if raw.get("scope") in _ALLOWED_SCOPES else "body",
    }


def _validate_patch(raw: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(raw, dict):
        return None
    patch: Dict[str, Any] = {}
    for key in _ALLOWED_PATCH_KEYS:
        if key not in raw:
            continue
        value = raw[key]
        if key == "name":
            cleaned = _clean_text(value, 200)
            if cleaned:
                patch["name"] = cleaned
        elif key == "params":
            if isinstance(value, dict):
                patch["params"] = value
        elif key == "severity":
            if value in _ALLOWED_SEVERITIES:
                patch["severity"] = value
        elif key == "type":
            if value in _ALLOWED_TYPES:
                patch["type"] = value
        elif key == "scope":
            if value in _ALLOWED_SCOPES:
                patch["scope"] = value
        elif key == "description":
            cleaned = _clean_text(value, 1000)
            if cleaned is not None:
                patch["description"] = cleaned
        elif key == "ai_prompt":
            cleaned = _clean_text(value, 1000)
            if cleaned is not None:
                patch["ai_prompt"] = cleaned
    return patch or None


def normalize_actions(
    items: List[Any],
    current_rules: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], int]:
    """Validate LLM actions against the current draft; returns (actions, rejected)."""
    known_ids = {str(rule.get("temp_id") or "") for rule in current_rules}
    actions: List[Dict[str, Any]] = []
    rejected = 0
    for item in items:
        if len(actions) >= MAX_ACTIONS:
            break
        if not isinstance(item, dict):
            rejected += 1
            continue
        action_type = str(item.get("type") or "").strip().lower()
        explanation = _clean_text(item.get("explanation"), 500) or ""
        if action_type == "add":
            rule = _validate_add(item.get("rule"))
            if rule is None:
                rejected += 1
                continue
            actions.append({"type": "add", "rule": rule, "explanation": explanation})
        elif action_type == "modify":
            temp_id = str(item.get("temp_id") or "")
            patch = _validate_patch(item.get("patch"))
            if temp_id not in known_ids or patch is None:
                rejected += 1
                continue
            actions.append(
                {
                    "type": "modify",
                    "temp_id": temp_id,
                    "patch": patch,
                    "explanation": explanation,
                }
            )
        elif action_type == "delete":
            temp_id = str(item.get("temp_id") or "")
            if temp_id not in known_ids:
                rejected += 1
                continue
            actions.append({"type": "delete", "temp_id": temp_id, "explanation": explanation})
        elif action_type == "explain":
            if explanation:
                actions.append({"type": "explain", "explanation": explanation})
        else:
            rejected += 1
    return actions, rejected


async def refine_rules(
    current_rules: List[Dict[str, Any]],
    instruction: str,
    *,
    client: Any,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, str]]]:
    """Ask the LLM to turn a natural-language instruction into rule actions.

    Returns (validated_actions, warnings). Never raises for LLM problems —
    callers show the warnings and let the user retry.
    """
    warnings: List[Dict[str, str]] = []
    rules = current_rules[:MAX_RULES]
    rules_payload = [
        {
            "temp_id": rule.get("temp_id"),
            "name": rule.get("name"),
            "kind": rule.get("kind"),
            "params": rule.get("params"),
            "severity": rule.get("severity"),
            "description": rule.get("description"),
            "ai_prompt": rule.get("ai_prompt"),
            "type": rule.get("type"),
            "scope": rule.get("scope"),
        }
        for rule in rules
    ]
    prompt = _REFINE_PROMPT.format(
        rules=json.dumps(rules_payload, ensure_ascii=False),
        instruction=instruction[:MAX_INSTRUCTION_CHARS],
    )
    try:
        text = await client.complete(prompt)
    except Exception as exc:  # noqa: BLE001 — LLM failures must degrade gracefully
        warnings.append({"code": "llm_failed", "message": f"LLM 调用失败: {str(exc)[:300]}"})
        return [], warnings
    try:
        items = parse_refine_payload(text)
    except (RefineError, json.JSONDecodeError) as exc:
        warnings.append({"code": "llm_parse_failed", "message": f"LLM 响应解析失败: {exc}"})
        return [], warnings

    actions, rejected = normalize_actions(items, rules)
    if rejected:
        warnings.append(
            {
                "code": "refine_action_rejected",
                "message": f"{rejected} 条 AI 建议未通过校验，已丢弃",
            }
        )
    if not actions:
        warnings.append({"code": "refine_no_actions", "message": "AI 没有给出可执行的操作"})
    return actions, warnings


__all__ = [
    "RefineError",
    "normalize_actions",
    "parse_refine_payload",
    "refine_rules",
]
