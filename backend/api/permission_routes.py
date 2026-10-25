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
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from backend.data.settings_repo import SettingsRepository
from backend.domain.tool_names import (
    PLUGIN_TOOL_PREFIX,
    is_plugin_tool_reference,
    plugin_tool_belongs_to_plugin,
    plugin_tool_wildcard_for_plugin,
)
from backend.services.permission_gate import get_permission_gate
from backend.tools.permissions import (
    SETTINGS_KEY_RULES,
    PermissionRule,
    parse_rules,
    remember_session_rule,
)

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


class RememberDuration(str, Enum):
    """remember=true 时规则的存续范围（R105，与范围正交）。"""

    PERMANENT = "permanent"
    SESSION = "session"


class ApprovalAnswerBody(BaseModel):
    """POST answer 请求体。"""

    approved: bool
    remember: bool = False
    remember_scope: RememberScope = RememberScope.TOOL
    # R105：存续范围与覆盖范围正交——permanent（默认）写
    # settings 持久规则；session 只写进程内会话规则存储，
    # 永不落盘。老客户端不带此字段即默认 permanent。
    remember_duration: RememberDuration = RememberDuration.PERMANENT
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
    """删除一条已保存规则的请求体（R99 改按内容定位）。"""

    #: 要撤销规则的 tool_pattern。它只是「删哪一条」的选择子：
    #: 服务端只删存储中已存在且与请求体完全一致的一条，
    #: 永不据此新建或改写任何规则。
    tool_pattern: str
    decision: str

    class Config:
        extra = "forbid"


def _load_saved_rules() -> List[Dict[str, str]]:
    """读取当前生效的已保存规则（与 enforcer 构造口径一致）。"""
    return [
        rule.to_dict()
        for rule in parse_rules(SettingsRepository().get_json(SETTINGS_KEY_RULES))
    ]


def _plugin_status_index() -> Optional[Dict[str, str]]:
    """生命周期记录 {插件名: 状态} 索引；失败返回 None（R101）。

    标注是纯增强信息：插件库不可用时返回 None，上层据此
    整体跳过标注（归属全 null），不把「读不到」误报成
    「插件无记录」。管理器按请求构造，与 plugin_routes
    同口径，不缓存连接；索引成功但无插件时返回空 dict。
    """
    try:
        from backend.plugins.lifecycle import PluginLifecycleManager

        index: Dict[str, str] = {}
        for record in PluginLifecycleManager().list_plugins():
            status = record.status
            index[record.name] = (
                status.value if isinstance(status, Enum) else str(status)
            )
        return index
    except Exception as exc:  # noqa: BLE001 — 标注降级不阻塞规则管理
        logger.warning("插件状态读取失败，规则归属标注降级为空: %s", exc)
        return None


def _rule_plugin_owner(pattern: str, index: Dict[str, str]) -> Optional[str]:
    """pattern 在生命周期名单中的权威归属插件名（R101/R102 共用）。

    判定只用结构化命名空间：等于该插件的受限通配，或完整
    工具名落在该插件命名空间内。长名字先试：``a`` 与
    ``a__b`` 共存时 ``plugin__a__b__run`` 归更具体的
    ``a__b``，保证标注（R101）与按插件删除（R102）选出
    的集合严格一致。
    """
    for name in sorted(index, key=len, reverse=True):
        if pattern == plugin_tool_wildcard_for_plugin(
            name
        ) or plugin_tool_belongs_to_plugin(pattern, name):
            return name
    return None


def _rule_plugin_status(
    pattern: str, index: Dict[str, str]
) -> Tuple[Optional[str], Optional[str]]:
    """``(归属插件名, 标注状态)``——R101 标注与 R104 选集共用分类。

    有生命周期归属时状态取记录状态；无归属时全局插件
    通配记 ``all``、插件形状记 ``missing``，其余（内置
    工具等）返回 ``(None, None)``。
    """
    owner = _rule_plugin_owner(pattern, index)
    if owner is not None:
        return owner, index[owner]
    if pattern == PLUGIN_TOOL_PREFIX + "*":
        return None, "all"
    if is_plugin_tool_reference(pattern):
        return None, "missing"
    return None, None


def _annotate_rules_with_plugin_status(
    rules: List[Dict[str, str]],
) -> List[Dict[str, Any]]:
    """为响应视图逐条附带插件归属标注（R101 只读派生，永不落盘）。

    归属只认生命周期权威名单 + 结构化命名空间 helper，
    不按工具名字符串切分猜插件名。``plugin_status`` 除
    生命周期状态外有派生值：``all``（全局插件通配）、
    ``missing``（插件形状但无记录，此时 plugin_name
    恒 null —— 无权威记录不报名字）。
    """
    index = _plugin_status_index()
    annotated: List[Dict[str, Any]] = []
    for rule in rules:
        if index is None:
            plugin_name, plugin_status = None, None
        else:
            plugin_name, plugin_status = _rule_plugin_status(
                rule["tool_pattern"], index
            )
        annotated.append(
            {**rule, "plugin_name": plugin_name, "plugin_status": plugin_status}
        )
    return annotated


@router.get("/rules")
def list_permission_rules() -> Dict[str, Any]:
    """列出已保存且生效的权限规则（设置页「已记住的规则」数据源）。"""
    return {
        "ok": True,
        "rules": _annotate_rules_with_plugin_status(_load_saved_rules()),
    }


@router.post("/rules/delete")
def delete_permission_rule(body: PermissionRuleDeleteBody, request: Request):
    """按内容删除一条已保存规则，返回删除后的最新列表。

    服务端以 parse_rules 口径重新读取生效列表，删除第一条与请求体
    完全一致的 (tool_pattern, decision)；无匹配 → 400 且不写存储。
    相比 R97 的列表下标，内容定位不受期间 remember 追加引起的
    位置漂移影响，不会删到界面上选中的那条之外的规则；重复规则
    每次仍只删一条。删除是撤销持久信任的写操作，与 preset 写入
    共用 Origin 守卫。
    """
    forbidden = forbidden_origin_response(request)
    if forbidden is not None:
        return forbidden
    rules = _load_saved_rules()
    target = {"tool_pattern": body.tool_pattern, "decision": body.decision}
    if target not in rules:
        return JSONResponse(
            status_code=400,
            content={"ok": False, "error": "rule not found"},
        )
    removed = rules.pop(rules.index(target))
    SettingsRepository().set_json(SETTINGS_KEY_RULES, rules, category="permissions")
    logger.info(
        "已删除已保存审批规则: pattern=%s decision=%s (剩余 %d 条)",
        removed["tool_pattern"],
        removed["decision"],
        len(rules),
    )
    return {"ok": True, "rules": _annotate_rules_with_plugin_status(rules)}


@router.post("/rules/clear")
def clear_permission_rules(request: Request):
    """清空全部已保存规则（撤销全部持久信任），返回空列表（R100）。

    无请求体、不接受任何筛选参数：语义只有「全部」一种，
    永远只能把列表写空，不能借此按条件删除或改写规则。
    幂等：本无规则时仍返回 ok。存储里的无效条目随写回
    空列表一并消失，与逐条删除的规范化写回同性质。清空
    是撤销持久信任的写操作，与逐条删除共用 Origin 守卫。
    """
    forbidden = forbidden_origin_response(request)
    if forbidden is not None:
        return forbidden
    removed_count = len(_load_saved_rules())
    SettingsRepository().set_json(SETTINGS_KEY_RULES, [], category="permissions")
    logger.info("已清空全部已保存审批规则（清空前共 %d 条生效规则）", removed_count)
    return {"ok": True, "rules": []}


class PermissionRulesDeleteByPluginBody(BaseModel):
    """按插件删除其全部已保存规则的请求体（R102）。"""

    #: 权威插件名（必须命中生命周期记录）。只是「删谁的
    #: 规则」的身份选择子：删除集合由服务端按结构化归属
    #: 选出，客户端不传任何 pattern，永不新建或放宽规则。
    plugin_name: str

    class Config:
        extra = "forbid"


@router.post("/rules/delete-by-plugin")
def delete_permission_rules_by_plugin(
    body: PermissionRulesDeleteByPluginBody, request: Request
):
    """删除某个插件名下的全部已保存规则，返回最新列表（R102）。

    选择子是插件身份而非 pattern：名字不在册 → 400 不写
    （含已卸载记录——清理孤儿规则正是主场景）；索引不可
    读 → 503 不写（校验不了身份就不做写操作）。删除集合
    与 R101 标注同源（``_rule_plugin_owner``，长名字消歧），
    只可能删掉该插件的现存规则。幂等：该插件本无规则时
    removed=0 返回 ok 且不写存储。与其它规则写操作共用
    Origin 守卫。
    """
    forbidden = forbidden_origin_response(request)
    if forbidden is not None:
        return forbidden
    index = _plugin_status_index()
    if index is None:
        return JSONResponse(
            status_code=503,
            content={"ok": False, "error": "plugin index unavailable"},
        )
    if body.plugin_name not in index:
        return JSONResponse(
            status_code=400,
            content={"ok": False, "error": "plugin not found"},
        )
    rules = _load_saved_rules()
    kept = [
        rule
        for rule in rules
        if _rule_plugin_owner(rule["tool_pattern"], index) != body.plugin_name
    ]
    removed_count = len(rules) - len(kept)
    if removed_count:
        SettingsRepository().set_json(
            SETTINGS_KEY_RULES, kept, category="permissions"
        )
    logger.info(
        "已删除插件 %s 的已保存审批规则 %d 条 (剩余 %d 条)",
        body.plugin_name,
        removed_count,
        len(kept),
    )
    return {
        "ok": True,
        "removed": removed_count,
        "rules": _annotate_rules_with_plugin_status(kept),
    }


@router.post("/rules/delete-orphans")
def delete_permission_orphan_rules(request: Request):
    """删除全部无生命周期归属的插件形规则，返回最新列表（R104）。

    与 delete-by-plugin 对称的另一半：missing 孤儿没有
    在册名字可做选择子，删除集合由服务端用与 R101 标注
    同一个分类口径（``_rule_plugin_status`` 的 missing
    类）选出，无请求体、不接受任何筛选参数，语义只有
    「全部 missing」一种。索引不可读 → 503 不写：分不
    清「无归属」与「读不到」时不删，避免把在册插件的
    规则误判为孤儿。全局插件通配与内置工具规则永远不
    在删除集合内。幂等：无孤儿时 removed=0 返回 ok 且
    不写存储。与其它规则写操作共用 Origin 守卫。
    """
    forbidden = forbidden_origin_response(request)
    if forbidden is not None:
        return forbidden
    index = _plugin_status_index()
    if index is None:
        return JSONResponse(
            status_code=503,
            content={"ok": False, "error": "plugin index unavailable"},
        )
    rules = _load_saved_rules()
    kept = [
        rule
        for rule in rules
        if _rule_plugin_status(rule["tool_pattern"], index)[1] != "missing"
    ]
    removed_count = len(rules) - len(kept)
    if removed_count:
        SettingsRepository().set_json(
            SETTINGS_KEY_RULES, kept, category="permissions"
        )
    logger.info(
        "已删除无归属插件孤儿审批规则 %d 条 (剩余 %d 条)",
        removed_count,
        len(kept),
    )
    return {
        "ok": True,
        "removed": removed_count,
        "rules": _annotate_rules_with_plugin_status(kept),
    }


def forbidden_origin_response(request: Request) -> JSONResponse | None:
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


def _derive_remembered_pattern(
    tool_name: str,
    remember_scope: RememberScope,
    plugin_name: Optional[str],
) -> Optional[str]:
    """remember 时的 pattern 安全派生（持久化/会话共用）。

    派生失败返回 None（只记 warning，调用方一律降级为不
    记住）：工具范围含 fnmatch 元字符（FIX-3，防 ``*``
    落成永久 allow-all），或整插件范围拿不到待审批请求
    自带的服务端权威插件名 / 工具不属于该插件（R95）。
    客户端在两种范围下都没有 pattern 表达能力。
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
            return None
        return pattern
    if _FNMATCH_METACHAR_RE.search(tool_name):
        logger.warning(
            "拒绝持久化含 fnmatch 元字符的审批规则（降级为不记住）: tool_name=%r",
            tool_name,
        )
        return None
    return tool_name


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

    R99 去重：完全相同的 (tool_pattern, decision) 已在存储中时
    不再重复落一条（只记 info、不写存储）；同 pattern 不同
    decision 照常追加，冲突仍由 enforcer 的 deny > allow > ask
    裁决，不借去重静默推翻先前落定的决定。

    其它失败也只记 warning——规则持久化失败不应让"已批准"的应答对前端
    变失败（本次执行已经放行了）。
    """
    pattern = _derive_remembered_pattern(tool_name, remember_scope, plugin_name)
    if pattern is None:
        return
    decision = "allow" if approved else "deny"
    try:
        repo = SettingsRepository()
        existing = parse_rules(repo.get_json(SETTINGS_KEY_RULES))
        rules_payload: List[Dict[str, Any]] = [r.to_dict() for r in existing]
        new_rule = {"tool_pattern": pattern, "decision": decision}
        if new_rule in rules_payload:
            logger.info(
                "审批规则已存在，跳过重复持久化: pattern=%s decision=%s scope=%s",
                pattern,
                decision,
                remember_scope.value,
            )
            return
        rules_payload.append(new_rule)
        repo.set_json(SETTINGS_KEY_RULES, rules_payload, category="permissions")
        logger.info(
            "已持久化审批规则: pattern=%s decision=%s scope=%s (共 %d 条)",
            pattern,
            decision,
            remember_scope.value,
            len(rules_payload),
        )
    except Exception as exc:  # noqa: BLE001 — 持久化失败不阻塞应答
        logger.warning("持久化审批规则失败: %s", exc)


def _store_session_remembered_rule(
    tool_name: str,
    approved: bool,
    *,
    remember_scope: RememberScope,
    plugin_name: Optional[str],
    session_id: Optional[str],
) -> None:
    """remember=true（仅本次会话）时把决定写进会话规则存储（R105）。

    与持久化共用同一 pattern 安全闸（``_derive_remembered_pattern``），
    从不写 settings。审批请求没有捕获到会话归属时降级为不
    记住（只记 warning）：用户选了「仅本次会话」就绝不能悄
    悄变成永久规则。``session_id`` 来自请求创建时的服务端
    上下文捕获，客户端不可指定。
    """
    if not session_id:
        logger.warning(
            "拒绝会话记住（审批请求无会话归属，降级为不记住）: tool_name=%r",
            tool_name,
        )
        return
    pattern = _derive_remembered_pattern(tool_name, remember_scope, plugin_name)
    if pattern is None:
        return
    decision = "allow" if approved else "deny"
    added = remember_session_rule(session_id, PermissionRule(pattern, decision))
    logger.info(
        "会话审批规则%s: session=%s pattern=%s decision=%s scope=%s",
        "已记录" if added else "已存在（跳过）",
        session_id,
        pattern,
        decision,
        remember_scope.value,
    )


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
        if body.remember_duration is RememberDuration.SESSION:
            _store_session_remembered_rule(
                req.tool_name,
                body.approved,
                remember_scope=body.remember_scope,
                plugin_name=req.plugin_name,
                session_id=req.session_id,
            )
        else:
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
