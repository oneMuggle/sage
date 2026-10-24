"""工具审批 REST 路由（M1 工具安全加固）。

前端契约（与 agent 流的 ``permission_request`` 事件配套）:

- ``GET /api/v1/permissions/pending``
    → ``[ApprovalRequest, ...]``（JSON 列表，形态同流事件的
    ``permission_request`` 字段；断线重连后用来补拉挂起对话框）。

- ``POST /api/v1/permissions/{request_id}/answer``
    body ``{"approved": bool, "remember": bool,
    "remember_scope": "tool"|"plugin"}``
    → ``{"ok": true}`` 或 ``{"ok": false, "error": "<reason>"}``

- ``GET /api/v1/permissions/rules`` → 当前生效的已保存规则列表
  （R97 设置页查看）；``POST /api/v1/permissions/rules/delete``
  body ``{"index": int}`` 逐条删除并返回最新列表。规则仍只能
  由审批 remember 生成，管理端点不接受任何 pattern 写入。

``remember=true`` 时把决定追加进 settings ``permission_rules``，
下次 agent 运行构造 enforcer 时生效。默认 ``tool`` 范围仍落
精确工具名；R95 的 ``plugin`` 范围只把服务端待审批请求中的
权威插件名派生为 ``plugin__<plugin>__*``，客户端不能提交
pattern 或插件名。

安全加固（安全评审 FIX-3 / FIX-4）:

- remember 持久化拒绝含 fnmatch 元字符（``* ? [ ]``）的工具名——工具名
  来自 LLM 工具调用，若把 ``"*"`` 落成规则等于永久 allow-all。
  整插件范围是唯一例外，但其 ``*`` 只能由服务端在校验权威
  插件名与完整工具名归属后生成；校验失败不落任何规则。
- 两个端点自带定向 Origin 守卫：带 ``Origin`` 头且不在白名单 → 403。
  背景：后端既有 CORS 配置是 ``allow_origins=["*"]``（全局问题，不在本
  里程碑内改），因此审批这种高权限端点必须自己挡住第三方网页的
  drive-by 请求。无 ``Origin`` 头（同源 / curl / python）放行——本地
  桌面应用的常态。
"""

from __future__ import annotations

import logging
import re
from enum import Enum
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from backend.data.settings_repo import SettingsRepository
from backend.domain.tool_names import (
    plugin_tool_belongs_to_plugin,
    plugin_tool_wildcard_for_plugin,
)
from backend.services.permission_gate import get_permission_gate
from backend.tools.permissions import SETTINGS_KEY_RULES, parse_rules

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/permissions", tags=["permissions"])

#: fnmatch 元字符——remember 持久化的 tool_pattern 含这些字符即拒绝。
#: 规则层用 fnmatch 匹配工具名，``"*"`` 会变成匹配一切工具的 allow-all
#: 规则（通配符规则注入）；``?`` / ``[ ]`` 同理可构造宽匹配。
_FNMATCH_METACHAR_RE = re.compile(r"[*?\[\]]")

#: 审批路由的 Origin 白名单。Electron 开发模式 ``loadURL`` 加载
#: ``http://localhost:1420``（见 electron/main.ts VITE_DEV_URL），打包后
#: ``loadFile`` 的 Origin 为 ``file://``；tauri 两形态为兼容保留。
_ALLOWED_ORIGINS = frozenset(
    {
        "http://localhost:1420",
        "http://127.0.0.1:1420",
        "file://",
        "tauri://localhost",
        "https://tauri.localhost",
    }
)


class RememberScope(str, Enum):
    """remember=true 时持久规则的覆盖范围。"""

    TOOL = "tool"
    PLUGIN = "plugin"


class ApprovalAnswerBody(BaseModel):
    """POST answer 请求体。"""

    approved: bool
    remember: bool = False
    remember_scope: RememberScope = RememberScope.TOOL
    # 对标 ZCode freeText：拒绝时用户附带的文字反馈（≤500 字符），
    # 经 gate → agent 拼进拒绝 reason，模型据此调整方案。批准时可留空。
    reason: str = Field(default="", max_length=500)

    class Config:
        # pydantic v1/v2 双兼容写法（Win7 LTS 分支用 v1）；
        # v2-only 的 ConfigDict / model_config 会在 v1 下静默失效。
        extra = "forbid"


# ---- 对标 S3（2026-09-13）：权限三档 + 会话自动放行审计 -------------------

#: 三档 → 既有 permission_mode 的映射（零后端语义改动）。
#: careful=谨慎（写/执行/网络都问）、standard=标准（工作区内写不问）、
#: auto=自动（只有破坏性命令仍经安全网审批）。
PERMISSION_PRESETS: Dict[str, str] = {
    "careful": "prompt",
    "standard": "workspace_write",
    "auto": "full_access",
}
_MODE_TO_PRESET: Dict[str, str] = {v: k for k, v in PERMISSION_PRESETS.items()}


class PermissionPresetBody(BaseModel):
    preset: str

    class Config:
        extra = "forbid"


@router.get("/preset")
def get_permission_preset() -> Dict[str, Any]:
    """当前权限三档（由 permission_mode 反推；read_only 映射为 careful 并标记 custom）。"""
    from backend.tools.permissions import DEFAULT_PERMISSION_MODE, SETTINGS_KEY_MODE

    raw = SettingsRepository().get(SETTINGS_KEY_MODE) or DEFAULT_PERMISSION_MODE.value
    mode = str(raw)
    preset = _MODE_TO_PRESET.get(mode)
    return {
        "preset": preset or "careful",
        "mode": mode,
        "custom": preset is None,
        "presets": PERMISSION_PRESETS,
    }


@router.post("/preset")
def set_permission_preset(body: PermissionPresetBody, request: Request):
    forbidden = forbidden_origin_response(request)
    if forbidden is not None:
        return forbidden
    mode = PERMISSION_PRESETS.get(body.preset)
    if mode is None:
        return JSONResponse(
            status_code=400,
            content={"ok": False, "error": f"unknown preset: {body.preset}"},
        )
    from backend.tools.permissions import SETTINGS_KEY_MODE

    SettingsRepository().set(SETTINGS_KEY_MODE, mode, category="permissions")
    return {"ok": True, "preset": body.preset, "mode": mode}


@router.get("/session/{session_id}/auto-approvals")
def list_session_auto_approvals(
    session_id: str, limit: int = 50, side_effect_only: bool = True
) -> Dict[str, Any]:
    """本会话未经确认即放行的工具调用（"已自动批准 N 次"数据源）。"""
    from backend.services.auto_approval_ledger import get_auto_approval_ledger

    ledger = get_auto_approval_ledger()
    items = ledger.list(session_id, limit=min(max(limit, 1), 200), side_effect_only=side_effect_only)
    return {
        "session_id": session_id,
        "count": ledger.count(session_id, side_effect_only=side_effect_only),
        "total": ledger.count(session_id, side_effect_only=False),
        "items": [i.to_dict() for i in items],
    }


@router.get("/trust-policy")
def get_trust_policy() -> Dict[str, Any]:
    """P2-5 渐进式授权：读取当前策略 + 各工具的连续人工批准次数。

    暴露计数是为了让用户**看得见**「哪些工具已经攒够信任」，而不是被静默
    自动放行 —— 渐进式授权最容易被质疑的就是「它凭什么替我点同意」。
    """
    from backend.services.trust_escalation import (
        DEFAULT_TRUST_THRESHOLD,
        SETTINGS_KEY_ENABLED,
        SETTINGS_KEY_THRESHOLD,
        load_trust_policy,
    )

    enabled, threshold = load_trust_policy()
    tools: Dict[str, int] = {}
    try:
        from backend.data.approval_decision_repo import ApprovalDecisionRepository

        repo = ApprovalDecisionRepository()
        for decision in repo.list(limit=200):
            if (decision.answered_by or "") != "gui":
                continue
            if not decision.session_id or not decision.tool_name:
                continue
            key = f"{decision.session_id}|{decision.tool_name}"
            if key not in tools:
                tools[key] = repo.consecutive_gui_approvals(
                    decision.session_id, decision.tool_name
                )
    except Exception as exc:  # noqa: BLE001 — 计数失败不影响策略读取
        logger.warning("trust 计数读取失败（忽略）: %s", exc)

    return {
        "ok": True,
        "enabled": enabled,
        "threshold": threshold,
        "default_threshold": DEFAULT_TRUST_THRESHOLD,
        "settings_keys": {
            "enabled": SETTINGS_KEY_ENABLED,
            "threshold": SETTINGS_KEY_THRESHOLD,
        },
        # 键为 "session_id|tool_name"，值 = 连续人工批准次数
        "consecutive": tools,
    }


class TrustPolicyBody(BaseModel):
    """P2-5 渐进式授权策略写入体。"""

    enabled: bool
    threshold: Optional[int] = None


@router.post("/trust-policy")
def set_trust_policy(body: TrustPolicyBody) -> Dict[str, Any]:
    """P2-5：开关渐进式授权。默认关闭，必须由用户显式开启。"""
    from backend.data.settings_repo import SettingsRepository
    from backend.services.trust_escalation import (
        DEFAULT_TRUST_THRESHOLD,
        SETTINGS_KEY_ENABLED,
        SETTINGS_KEY_THRESHOLD,
    )

    threshold = body.threshold if body.threshold is not None else DEFAULT_TRUST_THRESHOLD
    threshold = max(1, min(int(threshold), 20))
    repo = SettingsRepository()
    repo.set(SETTINGS_KEY_ENABLED, "1" if body.enabled else "0", category="permissions")
    repo.set(SETTINGS_KEY_THRESHOLD, str(threshold), category="permissions")
    return {"ok": True, "enabled": body.enabled, "threshold": threshold}


# ---- R97：已保存权限规则的查看 / 逐条删除 -----------------------------------
#
# 规则只能由审批 remember 生成（精确工具名，或服务端按权威插件名派生
# 的整插件受限通配）；这里只补「看得见、删得掉」，不提供新增/编辑
# pattern 的入口。列表口径与求值同源：同一个 parse_rules()，存储里的
# 非法条目本来就不参与求值，UI 也不展示；删除写回时顺带规范化清理。


class PermissionRuleDeleteBody(BaseModel):
    """删除一条已保存规则的请求体。"""

    #: 下标指 GET /rules 返回的已解析规则列表。
    index: int

    class Config:
        extra = "forbid"


def _load_saved_rules() -> List[Dict[str, str]]:
    """读取当前生效的已保存规则（与 enforcer 构造口径一致）。"""
    return [
        rule.to_dict()
        for rule in parse_rules(SettingsRepository().get_json(SETTINGS_KEY_RULES))
    ]


@router.get("/rules")
def list_permission_rules() -> Dict[str, Any]:
    """列出已保存且生效的权限规则（设置页「已记住的规则」数据源）。"""
    return {"ok": True, "rules": _load_saved_rules()}


@router.post("/rules/delete")
def delete_permission_rule(body: PermissionRuleDeleteBody, request: Request):
    """按下标删除一条已保存规则，返回删除后的最新列表。

    服务端重新读取并校验下标，越界 → 400 且不写存储；重复规则只
    删被指中的一条。删除是撤销持久信任的写操作，与 preset 写入
    共用 Origin 守卫。
    """
    forbidden = forbidden_origin_response(request)
    if forbidden is not None:
        return forbidden
    rules = _load_saved_rules()
    if body.index < 0 or body.index >= len(rules):
        return JSONResponse(
            status_code=400,
            content={"ok": False, "error": "rule index out of range"},
        )
    removed = rules.pop(body.index)
    SettingsRepository().set_json(SETTINGS_KEY_RULES, rules, category="permissions")
    logger.info(
        "已删除已保存审批规则: pattern=%s decision=%s (剩余 %d 条)",
        removed["tool_pattern"],
        removed["decision"],
        len(rules),
    )
    return {"ok": True, "rules": rules}


def forbidden_origin_response(request: Request) -> Optional[JSONResponse]:
    """Origin 守卫：带 Origin 头且不在白名单 → 403 响应；否则 None（放行）。

    无 ``Origin`` 头视为同源 / 非浏览器客户端（curl、python、Electron
    同源请求），直接放行——本应用是本地桌面后端，不依赖浏览器 CORS 预检。

    本守卫供所有高权限 gate 路由复用（M2 part B: question_routes 导入本
    函数，不复制实现）。
    """
    origin = request.headers.get("origin")
    if origin is not None and origin not in _ALLOWED_ORIGINS:
        logger.warning(
            "审批路由拒绝非白名单 Origin: origin=%s path=%s", origin, request.url.path
        )
        return JSONResponse(
            status_code=403,
            content={"ok": False, "error": "forbidden_origin"},
        )
    return None


def _persist_remembered_rule(
    tool_name: str,
    approved: bool,
    *,
    remember_scope: RememberScope = RememberScope.TOOL,
    plugin_name: Optional[str] = None,
) -> None:
    """remember=true 时把决定追加为持久化规则。

    安全闸（FIX-3）: ``tool_name`` 含 fnmatch 元字符（``* ? [ ]``）时
    静默降级为不记住——工具名来自 LLM 工具调用，原样落成 fnmatch pattern
    会让 ``"*"`` 变成永久 allow-all 规则。本次应答照常成功（approved 已
    作用于当次请求），只是不持久化，并记 warning。

    R95 整插件范围不接受任何客户端 pattern：只有待审批请求
    自带的服务端 ``plugin_name`` 能派生受限通配，且完整工具
    名必须确实属于该插件；否则同样只记 warning、不落规则。

    其它失败也只记 warning——规则持久化失败不应让"已批准"的应答对前端
    变失败（本次执行已经放行了）。
    """
    if remember_scope is RememberScope.PLUGIN:
        pattern = plugin_tool_wildcard_for_plugin(plugin_name)
        if pattern is None or not plugin_tool_belongs_to_plugin(
            tool_name, plugin_name
        ):
            logger.warning(
                "拒绝持久化整插件审批规则（权威插件名缺失或不匹配）: "
                "tool_name=%r plugin_name=%r",
                tool_name,
                plugin_name,
            )
            return
    elif _FNMATCH_METACHAR_RE.search(tool_name):
        logger.warning(
            "拒绝持久化含 fnmatch 元字符的审批规则（降级为不记住）: tool_name=%r",
            tool_name,
        )
        return
    else:
        pattern = tool_name
    try:
        repo = SettingsRepository()
        existing = parse_rules(repo.get_json(SETTINGS_KEY_RULES))
        rules_payload: List[Dict[str, Any]] = [r.to_dict() for r in existing]
        rules_payload.append(
            {
                "tool_pattern": pattern,
                "decision": "allow" if approved else "deny",
            }
        )
        repo.set_json(SETTINGS_KEY_RULES, rules_payload, category="permissions")
        logger.info(
            "已持久化审批规则: pattern=%s decision=%s scope=%s (共 %d 条)",
            pattern,
            "allow" if approved else "deny",
            remember_scope.value,
            len(rules_payload),
        )
    except Exception as exc:  # noqa: BLE001 — 持久化失败不阻塞应答
        logger.warning("持久化审批规则失败: %s", exc)


@router.get("/pending")
async def list_pending_approvals(request: Request) -> List[Dict[str, Any]]:
    """列出当前挂起的审批请求（gate 未初始化时返回空列表）。"""
    forbidden = forbidden_origin_response(request)
    if forbidden is not None:
        return forbidden  # type: ignore[return-value]
    gate = get_permission_gate()
    if gate is None:
        return []
    return [req.to_dict() for req in gate.pending()]


@router.post("/{request_id}/answer")
async def answer_approval(
    request_id: str, body: ApprovalAnswerBody, request: Request
) -> Dict[str, Any]:
    """应答一个挂起的审批请求。

    错误语义（HTTP 恒为 200，ok 字段区分成败——与前端既有流式错误处理一致；
    Origin 守卫例外，返回真正的 403）:

    - Origin 不在白名单      → HTTP 403 ``{"ok": false, "error": "forbidden_origin"}``
    - gate 未初始化          → ``{"ok": false, "error": "permission_gate_not_initialized"}``
    - id 未知 / 已过期       → ``{"ok": false, "error": "unknown_or_expired"}``
    """
    forbidden = forbidden_origin_response(request)
    if forbidden is not None:
        return forbidden  # type: ignore[return-value]

    gate = get_permission_gate()
    if gate is None:
        return {"ok": False, "error": "permission_gate_not_initialized"}

    req = gate.get_request(request_id)
    if req is None:
        return {"ok": False, "error": "unknown_or_expired"}

    resolved = gate.answer(request_id, body.approved, body.remember, reason=body.reason)
    if not resolved:
        return {"ok": False, "error": "unknown_or_expired"}

    if body.remember:
        _persist_remembered_rule(
            req.tool_name,
            body.approved,
            remember_scope=body.remember_scope,
            plugin_name=req.plugin_name,
        )

    # live-events P1: 子代理审批回填 —— 命中编排 run 时回发
    # ``task.approval_resolved``（canonical）+ ``subagent_event`` 镜像
    # （聊天），任务树 live 行从"等待审批"切回执行态。best-effort：
    # 未命中（主 agent 审批）或通道失败都不影响应答结果。
    try:
        from backend.orchestration.chat_dispatcher import find_dispatcher_for_approval

        dispatcher = find_dispatcher_for_approval(request_id)
        if dispatcher is not None:
            await dispatcher.resolve_approval(request_id, body.approved)
    except Exception as exc:  # noqa: BLE001 — 回填失败不阻塞应答
        logger.warning("子代理审批回填失败 request_id=%s: %s", request_id, exc)

    return {"ok": True}


__all__ = ["router", "forbidden_origin_response"]
