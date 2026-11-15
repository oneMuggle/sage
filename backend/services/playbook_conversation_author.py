"""Conversational playbook authoring (2026-11-14).

Unlike ``playbook_author`` (one-shot questionnaire -> draft), this engine keeps
a multi-turn conversation so the user can iteratively reshape the project's
stages in natural language ("把第二阶段拆成两个", "加一个评审节点"). Every
assistant turn stores the playbook draft as of that turn, which makes rollback
a simple restore of an earlier snapshot.

The deterministic fallback never mutates the draft: if the LLM is unavailable
the user still sees the current stages and can commit them.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from backend.data.playbook_author_conversation_repo import (
    STATUS_ACTIVE,
    AuthorConversation,
    PlaybookAuthorConversationRepository,
)
from backend.data.playbook_repo import PlaybookRepository
from backend.services.llm_json import parse_json
from backend.services.playbook_author import build_author_preview
from backend.services.playbook_spec import PlaybookValidationError, normalize_playbook

logger = logging.getLogger(__name__)

MAX_TURNS = 20
MAX_MESSAGE_TEXT = 2000
HISTORY_WINDOW = 8


@dataclass
class AuthorTurnResult:
    """Outcome of one user turn in an authoring conversation."""

    conversation: Dict[str, Any]
    reply: str
    playbook: Optional[Dict[str, Any]]
    llm_available: bool
    source: str
    turn_index: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "conversation": self.conversation,
            "reply": self.reply,
            "playbook": self.playbook,
            "llm_available": self.llm_available,
            "source": self.source,
            "turn_index": self.turn_index,
        }


def _now_ms() -> int:
    return int(time.time() * 1000)


def _next_turn_index(messages: List[Dict[str, Any]]) -> int:
    """Turn 0 is the seeded draft; user turns start at 1."""
    turns = [int(item.get("turn_index") or 0) for item in messages]
    return (max(turns) + 1) if turns else 1


def _stage_summary(spec: Optional[Dict[str, Any]]) -> str:
    stages = (spec or {}).get("stages") or []
    if not stages:
        return "（当前还没有阶段）"
    lines = []
    for index, stage in enumerate(stages, start=1):
        label = stage.get("label") or stage.get("id") or f"阶段 {index}"
        artifacts = [
            item.get("label")
            for item in stage.get("artifacts") or []
            if item.get("label")
        ]
        artifact_text = f"：{'、'.join(artifacts)}" if artifacts else ""
        lines.append(f"{index}. {label}{artifact_text}")
    return "\n".join(lines)


def _greeting(project: Any, spec: Dict[str, Any]) -> str:
    type_label = (
        getattr(project, "project_type", None)
        or getattr(project, "detected_type", None)
        or "未分类"
    )
    return (
        f"你好！我来帮你定制「{getattr(project, 'name', '') or '这个项目'}」的规程。"
        f"根据项目类型（{type_label}）我先给了一份参考草案：\n\n"
        f"{_stage_summary(spec)}\n\n"
        "请描述你的实际管理流程——分几个阶段、每个阶段要交付什么、有哪些检查点。"
        "之后可以直接说「把第二阶段拆成两个」「给结题阶段加一个查重」来调整。"
    )


def _compact_spec(spec: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    spec = spec or {}
    return {
        "id": spec.get("id"),
        "name": spec.get("name"),
        "description": spec.get("description"),
        "directory_layout": [
            {"path": item.get("path"), "required": item.get("required", True)}
            for item in spec.get("directory_layout") or []
        ],
        "stages": [
            {
                "id": stage.get("id"),
                "label": stage.get("label"),
                "order": stage.get("order"),
                "objective": stage.get("objective"),
                "artifacts": [
                    {"label": item.get("label"), "required": item.get("required", True)}
                    for item in stage.get("artifacts") or []
                ],
            }
            for stage in spec.get("stages") or []
        ],
    }


def _build_prompt(
    project: Any,
    current_spec: Optional[Dict[str, Any]],
    messages: List[Dict[str, Any]],
    user_message: str,
) -> str:
    history = [
        {
            "role": item.get("role"),
            "content": str(item.get("content") or "")[:MAX_MESSAGE_TEXT],
        }
        for item in messages[-HISTORY_WINDOW:]
        if item.get("role") in ("user", "assistant")
    ]
    return f"""你是项目管理方法论专家，正在和一个用户通过对话定制项目规程（Playbook）。

## 项目
- 名称: {getattr(project, 'name', '')}
- 类型: {getattr(project, 'project_type', None) or getattr(project, 'detected_type', None) or '未分类'}
- 子类型: {getattr(project, 'project_sub_type', None) or '未指定'}
- 描述: {getattr(project, 'description', None) or '无'}

## 当前规程草案
{json.dumps(_compact_spec(current_spec), ensure_ascii=False)}

## 最近对话
{json.dumps(history, ensure_ascii=False)}

## 用户最新消息
{user_message}

## 输出要求
只输出一个 JSON 对象，不要 Markdown 围栏：
{{"reply": "用中文简明回答用户，并说明本次改了哪些阶段", "playbook": {{
  "schema_version": "1.0",
  "id": "custom-xxx",
  "name": "规程名称",
  "description": "适用范围",
  "applies_to": {{"project_types": ["coding|research|business|personal"], "sub_types": []}},
  "directory_layout": [{{"path": "01_开题", "required": true, "purpose": "用途"}}],
  "stages": [
    {{"id": "stage-id", "label": "阶段名", "order": 1, "objective": "目标",
      "artifacts": [{{"id": "artifact-id", "label": "文档名", "required": true,
        "match": {{"globs": ["**/文档名*"], "min_count": 1}}}}],
      "exit_criteria": [], "rules": [], "recommended_milestones": []}}
  ],
  "global_rules": [], "todos": [], "ai_guidance": {{}}, "meta": {{}}
}}}}

约束：
- 输出完整规程：保留用户没有要求改动的阶段与产物。
- 阶段 1-12 个，每个阶段 0-8 个产物；globs 使用项目根相对路径。
- 用户只是提问、不需要改草案时，playbook 原样返回当前草案。
- 不要包含任何项目文件内容或敏感信息。
"""


class PlaybookConversationAuthor:
    """Multi-turn authoring engine backed by the conversation repository."""

    def __init__(
        self,
        repo: Optional[PlaybookAuthorConversationRepository] = None,
        playbook_repo: Optional[PlaybookRepository] = None,
    ) -> None:
        self.repo = repo or PlaybookAuthorConversationRepository()
        self.playbook_repo = playbook_repo or PlaybookRepository()

    async def start(self, project: Any) -> AuthorConversation:
        """Open a new conversation seeded with a deterministic reference draft."""
        base_result = await build_author_preview(project, use_llm=False)
        base_spec = base_result.playbook
        now_ms = _now_ms()
        messages: List[Dict[str, Any]] = [
            {
                "role": "assistant",
                "content": _greeting(project, base_spec),
                "turn_index": 0,
                "playbook_snapshot": base_spec,
                "created_at": now_ms,
            }
        ]
        return self.repo.create(
            str(getattr(project, "id", "")),
            spec=base_spec,
            messages=messages,
        )

    async def send_message(
        self,
        project: Any,
        conversation: AuthorConversation,
        user_message: str,
        *,
        use_llm: bool = True,
        llm_client: Any = None,
    ) -> AuthorTurnResult:
        """Record a user turn and return the AI reply plus the updated draft."""
        text = str(user_message or "").strip()[:MAX_MESSAGE_TEXT]
        if not text:
            raise ValueError("消息不能为空")

        turn_index = _next_turn_index(conversation.messages)
        if turn_index > MAX_TURNS:
            raise ValueError(f"对话轮次已达上限（{MAX_TURNS} 轮），请先确认或结束当前对话")

        current_spec = conversation.current_spec
        conversation.messages.append(
            {
                "role": "user",
                "content": text,
                "turn_index": turn_index,
                "playbook_snapshot": None,
                "created_at": _now_ms(),
            }
        )

        client = llm_client
        if client is None and use_llm:
            client = self._build_client()

        reply, spec, llm_available, source = self._fallback_reply(
            current_spec, client is None
        )
        if client is not None:
            try:
                raw = await client.complete(
                    _build_prompt(project, current_spec, conversation.messages[:-1], text)
                )
                payload = parse_json(raw)
                if not isinstance(payload, dict):
                    raise PlaybookValidationError("LLM 未返回 JSON 对象")
                reply = (
                    str(payload.get("reply") or "").strip()
                    or "已根据你的要求更新规程草案。"
                )
                candidate = payload.get("playbook")
                if candidate:
                    spec = normalize_playbook(candidate)
                llm_available = True
                source = "llm"
            except Exception:  # noqa: BLE001 — fall back without mutating the draft
                logger.warning(
                    "LLM conversation authoring failed, keeping draft", exc_info=True
                )

        conversation.messages.append(
            {
                "role": "assistant",
                "content": reply,
                "turn_index": turn_index,
                "playbook_snapshot": spec,
                "created_at": _now_ms(),
            }
        )
        conversation.current_spec = spec
        conversation.status = STATUS_ACTIVE
        self.repo.save(conversation)

        return AuthorTurnResult(
            conversation=conversation.to_dict(),
            reply=reply,
            playbook=spec,
            llm_available=llm_available,
            source=source,
            turn_index=turn_index,
        )

    def rollback(
        self, conversation: AuthorConversation, turn_index: int
    ) -> Tuple[AuthorConversation, Optional[Dict[str, Any]]]:
        """Restore the draft captured at the given turn and drop later messages."""
        target: Optional[Dict[str, Any]] = None
        keep_until = -1
        for index, item in enumerate(conversation.messages):
            if int(item.get("turn_index") or 0) != turn_index:
                continue
            if item.get("role") != "assistant":
                continue
            if item.get("playbook_snapshot") is None:
                continue
            target = item.get("playbook_snapshot")
            keep_until = index
        if target is None:
            raise ValueError(f"第 {turn_index} 轮没有可回退的规程快照")

        conversation.messages = conversation.messages[: keep_until + 1]
        conversation.current_spec = target
        self.repo.save(conversation)
        return conversation, target

    def commit(
        self, project_id: str, conversation: AuthorConversation
    ) -> Dict[str, Any]:
        """Bind the current draft as the project's active playbook snapshot."""
        spec = conversation.current_spec
        if not spec:
            raise ValueError("当前对话还没有可绑定的规程草案")
        snapshot = self.playbook_repo.create_snapshot(
            project_id, spec, source="ai-authored"
        )
        conversation.status = "committed"
        self.repo.save(conversation)
        return {"snapshot": snapshot.to_dict(), "conversation": conversation.to_dict()}

    @staticmethod
    def _build_client() -> Any:
        try:
            from backend.orchestration.llm_factory import build_llm_client_from_settings

            return build_llm_client_from_settings()
        except Exception:  # noqa: BLE001 — LLM is optional
            logger.warning(
                "failed to build LLM client for conversation authoring", exc_info=True
            )
            return None

    @staticmethod
    def _fallback_reply(
        current_spec: Optional[Dict[str, Any]], no_client: bool
    ) -> Tuple[str, Optional[Dict[str, Any]], bool, str]:
        if not no_client:
            return (
                "已收到你的要求，但 AI 本轮未能返回结果，规程草案保持不变。可以重试或直接确认。",
                current_spec,
                False,
                "deterministic",
            )
        return (
            "当前未配置可用的 AI 模型，无法自动调整规程。以下是现有草案，可直接确认，"
            "或到设置中配置模型后再继续：\n\n" + _stage_summary(current_spec),
            current_spec,
            False,
            "deterministic",
        )


__all__ = [
    "AuthorTurnResult",
    "MAX_MESSAGE_TEXT",
    "MAX_TURNS",
    "PlaybookConversationAuthor",
]
