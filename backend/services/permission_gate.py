"""工具审批闸口（M1 工具安全加固）。

当 ``PermissionEnforcer`` 判定某次工具调用 ``needs_approval`` 时，agent 循环
通过本模块挂起执行：

1. agent 侧调用 ``ApprovalGate.request(req, timeout)`` —— 注册一个 Future 并
   await（agent 流在 await 之前先 yield permission_request 事件给前端）。
2. 前端收到事件渲染对话框，用户点击后 POST /api/v1/permissions/{id}/answer。
3. 路由调用 ``ApprovalGate.answer(request_id, approved, remember)`` 解析 Future，
   agent 循环被唤醒继续执行或拒绝。
4. 超时未应答 → ``ApprovalAnswer(False, False, "timeout")``（fail-closed）。

单例装配遵循 ``backend.services.scheduler`` 的模式：``init_permission_gate()``
在 ``main.py`` lifespan 中调用一次，``get_permission_gate()`` 供路由 / agent
取用；未初始化时返回 ``None``，调用方按 default-deny 处理。

并发模型：sage 后端单事件循环，gate 的 dict 操作均在循环线程内，无需加锁。
``answer()`` 可能从路由 handler（同循环）调用，``request()`` 在 agent task 内
await——Future 跨 task 解析是 asyncio 的常规用法。
"""

from __future__ import annotations

import asyncio
import difflib
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

#: 单个参数值的最大展示长度（超出截断）
ARG_VALUE_MAX_CHARS = 200

#: 命中即脱敏的参数名模式（键名包含这些词的值一律替换为 ***）
_SECRET_KEY_RE = re.compile(r"(key|token|password|secret|credential|auth)", re.IGNORECASE)

#: 未指定超时时的默认等待秒数（5 分钟，与 claw-code 审批超时一致）
DEFAULT_APPROVAL_TIMEOUT_S = 300.0

# ==================== U15: 写类工具审批 diff 预览 ====================

#: diff 预览整体最大字符数（超出尾部截断，防撑爆流事件）
DIFF_PREVIEW_MAX_CHARS = 8000

#: 预览读取源文件的字节上限（超大文件只 diff 可见前缀）
_DIFF_READ_MAX_BYTES = 262144

#: 生成 diff 预览的写类工具集合
_DIFF_PREVIEW_TOOLS = frozenset({"write_file", "edit_file", "apply_patch"})


#: 脱敏递归深度上限——防自引用结构（``d["self"] = d``）导致无限递归；
#: 超限的嵌套子树整体替换为占位字符串，同时切断环路。
MAX_SCRUB_DEPTH = 5


def _scrub_value(value: Any, depth: int) -> Any:
    """递归脱敏：任意深度的 dict/list 里键名命中秘密模式的值 → ``"***"``。

    只处理容器结构（dict/list/tuple）；其它叶子值原样返回，由调用方
    统一字符串化 + 截断。深度超过 ``MAX_SCRUB_DEPTH`` 的容器整体替换为
    占位字符串——现实中的工具参数嵌套不会这么深，而这一封顶让循环
    引用结构不可能撑爆递归。
    """
    if isinstance(value, dict):
        if depth > MAX_SCRUB_DEPTH:
            return "…(超过嵌套深度上限)"
        scrubbed: Dict[str, Any] = {}
        for key, item in value.items():
            key_str = str(key)
            if _SECRET_KEY_RE.search(key_str):
                scrubbed[key_str] = "***"
            else:
                scrubbed[key_str] = _scrub_value(item, depth + 1)
        return scrubbed
    if isinstance(value, (list, tuple)):  # noqa: UP038 — py3.8 不支持 X | Y isinstance
        if depth > MAX_SCRUB_DEPTH:
            return "…(超过嵌套深度上限)"
        return [_scrub_value(item, depth + 1) for item in value]
    return value


def _resolve_preview_path(raw: str, workspace_root: Optional[str]) -> Optional[Path]:
    """把工具参数里的路径解析为可读路径；相对路径挂在 workspace 下。"""
    if not isinstance(raw, str) or not raw.strip():
        return None
    path = Path(raw)
    if not path.is_absolute() and workspace_root:
        path = Path(workspace_root) / path
    return path


def _read_text_capped(path: Path) -> Optional[str]:
    """读取现文件内容（截到 ``_DIFF_READ_MAX_BYTES``）；不存在/不可读返回 None。"""
    try:
        if not path.is_file():
            return None
        with open(path, "rb") as fh:
            data = fh.read(_DIFF_READ_MAX_BYTES)
        return data.decode("utf-8", errors="replace")
    except OSError:
        return None


def _unified_diff(label: str, before: str, after: str) -> str:
    """单文件 unified diff；无差异返回空串。"""
    return "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile="a/" + label,
            tofile="b/" + label,
        )
    )


def _collect_diff_sections(
    tool_name: str,
    args: Dict[str, Any],
    workspace_root: Optional[str],
) -> List[str]:
    """按工具语义收集各文件的 diff 片段（只读，不落盘）。"""
    sections: List[str] = []

    def _edit_section(raw_path: str, old: str, new: str, replace_all: bool) -> None:
        path = _resolve_preview_path(raw_path, workspace_root)
        if path is None:
            return
        current = _read_text_capped(path)
        if current is None:
            return
        after = current.replace(old, new) if replace_all else current.replace(old, new, 1)
        diff = _unified_diff(raw_path, current, after)
        if diff:
            sections.append(diff)

    if tool_name == "write_file":
        path = _resolve_preview_path(str(args.get("path") or ""), workspace_root)
        content = args.get("content")
        if path is None or not isinstance(content, str):
            return sections
        current = _read_text_capped(path)
        diff = _unified_diff(str(args.get("path")), current or "", content)
        if diff:
            sections.append(diff)
    elif tool_name == "edit_file":
        raw_path = args.get("file_path")
        old, new = args.get("old_string"), args.get("new_string")
        if isinstance(raw_path, str) and isinstance(old, str) and isinstance(new, str):
            _edit_section(raw_path, old, new, False)
    elif tool_name == "apply_patch":
        patches = args.get("patches")
        if isinstance(patches, list):
            for patch in patches:
                if not isinstance(patch, dict):
                    continue
                raw_path = patch.get("file_path")
                old, new = patch.get("old_string"), patch.get("new_string")
                if not isinstance(raw_path, str) or not isinstance(old, str) or not isinstance(new, str):
                    continue
                replace_all = bool(patch.get("replace_all"))
                _edit_section(raw_path, old, new, replace_all)
    return sections


def build_diff_preview(
    tool_name: str,
    args: Optional[Dict[str, Any]],
    workspace_root: Optional[str] = None,
) -> Optional[str]:
    """为写类工具生成将写入内容的 unified diff（U15 审批透明化）。

    - ``write_file``: 现文件（不存在视为空）vs ``args["content"]``
    - ``edit_file``: 现文件 vs ``old_string→new_string`` 替换一次后的结果
    - ``apply_patch``: 逐条 ``{file_path, old_string, new_string, replace_all?}``
      与 edit 同语义，多文件 diff 顺序拼接

    任何一步失败（参数缺失/路径不可读/编码异常）→ ``None``，审批回退展示
    ``args_summary``，绝不阻塞审批流。**本函数只读，不落盘**。
    """
    if not isinstance(args, dict) or tool_name not in _DIFF_PREVIEW_TOOLS:
        return None
    try:
        sections = _collect_diff_sections(tool_name, args, workspace_root)
    except Exception:  # noqa: BLE001 — 预览是尽力而为, 不阻塞审批
        logger.debug("diff 预览生成失败: tool=%s", tool_name, exc_info=True)
        return None
    if not sections:
        return None
    preview = "\n".join(sections)
    if len(preview) > DIFF_PREVIEW_MAX_CHARS:
        preview = preview[:DIFF_PREVIEW_MAX_CHARS] + "\n…(diff 已截断)"
    return preview


def summarize_tool_args(args: Optional[Dict[str, Any]]) -> str:
    """把工具参数压成可展示的 JSON 字符串。

    - 键名匹配 key/token/password/secret/credential/auth 的值 → ``"***"``，
      **递归进入嵌套 dict/list**（深度封顶 ``MAX_SCRUB_DEPTH``）——顶层
      脱敏挡不住 ``{"config": {"api_key": ...}}`` 这类嵌套泄漏。
    - 其余值字符串化后截断到 ``ARG_VALUE_MAX_CHARS``
    - 整体再兜底截断到 1000 字符，防止极端参数撑爆流事件
    """
    if not args:
        return "{}"
    clean: Dict[str, Any] = {}
    for key, value in args.items():
        key_str = str(key)
        if _SECRET_KEY_RE.search(key_str):
            clean[key_str] = "***"
            continue
        scrubbed = _scrub_value(value, 1)
        if isinstance(scrubbed, str):
            text = scrubbed
        else:
            try:
                text = json.dumps(scrubbed, ensure_ascii=False, default=str)
            except (TypeError, ValueError):
                text = str(scrubbed)
        if len(text) > ARG_VALUE_MAX_CHARS:
            text = text[:ARG_VALUE_MAX_CHARS] + "…(已截断)"
        clean[key_str] = text
    summary = json.dumps(clean, ensure_ascii=False)
    if len(summary) > 1000:
        summary = summary[:1000] + "…(已截断)"
    return summary


@dataclass(frozen=True)
class ApprovalAnswer:
    """审批应答（不可变）。

    Attributes:
        approved:    用户是否批准。
        remember:    是否把该决定持久化为规则（精确工具名 allow/deny）。
        answered_by: 应答来源——``"gui"`` / ``"timeout"`` / ``"default-deny"``。
    """

    approved: bool
    remember: bool
    answered_by: str


@dataclass(frozen=True)
class ApprovalRequest:
    """一次待审批的工具调用（不可变）。

    Attributes:
        request_id:   UUID，前端应答时回传。
        tool_name:    工具名（remember 时作为规则的精确 pattern）。
        args_summary: 已脱敏 + 截断的参数 JSON 字符串。
        risk:         风险等级（bash 校验结果或 "safe"）。
        message:      展示给用户的完整原因（来自 PermissionDecision.reason）。
        created_at:   创建时间（epoch 秒）。
        diff_preview: 写类工具的将写入内容 unified diff（U15）；
                      None = 无法生成（非写类工具 / 读取失败），回退 args_summary。
    """

    request_id: str
    tool_name: str
    args_summary: str
    risk: str
    message: str
    created_at: float
    diff_preview: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """流事件 / REST 响应共用的 JSON 形态。"""
        payload: Dict[str, Any] = {
            "request_id": self.request_id,
            "tool_name": self.tool_name,
            "args_summary": self.args_summary,
            "risk": self.risk,
            "message": self.message,
            "created_at": self.created_at,
        }
        if self.diff_preview:
            payload["diff_preview"] = self.diff_preview
        return payload

    @classmethod
    def create(
        cls,
        tool_name: str,
        args: Optional[Dict[str, Any]],
        risk: str,
        message: str,
        workspace_root: Optional[str] = None,
    ) -> ApprovalRequest:
        """工厂：生成 UUID + 时间戳 + 脱敏参数摘要 + 写类工具 diff 预览。"""
        return cls(
            request_id=str(uuid.uuid4()),
            tool_name=tool_name,
            args_summary=summarize_tool_args(args),
            risk=risk,
            message=message,
            created_at=time.time(),
            diff_preview=build_diff_preview(tool_name, args, workspace_root),
        )


#: C2 (2026-09-09): 审批 run/task 归属解析器 —— 由编排层在启动时经
#: ``set_approval_context_resolver`` 注册（依赖反转）。services 层不得直接
#: import orchestration（六边形 import 契约），故经此回调解耦；未注册时
#: run/task 归属为空（主会话审批本就无编排归属）。
ApprovalContextResolver = Callable[[str], Tuple[Optional[str], Optional[str]]]
_approval_context_resolver: Optional[ApprovalContextResolver] = None


def set_approval_context_resolver(resolver: ApprovalContextResolver) -> None:
    """注册 run/task 归属解析器（backend.main 启动时调用一次）。"""
    global _approval_context_resolver
    _approval_context_resolver = resolver


class ApprovalGate:
    """挂起 / 解析待审批请求的闸口。"""

    def __init__(self) -> None:
        self._pending: Dict[str, Tuple[ApprovalRequest, asyncio.Future[ApprovalAnswer]]] = {}

    async def request(
        self, req: ApprovalRequest, timeout: float = DEFAULT_APPROVAL_TIMEOUT_S
    ) -> ApprovalAnswer:
        """注册 req 并等待应答；超时返回 default-deny。

        调用方（agent 循环）负责在 await 本方法**之前**把 permission_request
        事件推入流，否则前端无从知晓该请求。
        """
        loop = asyncio.get_running_loop()
        future: asyncio.Future[ApprovalAnswer] = loop.create_future()
        self._pending[req.request_id] = (req, future)
        registered_ms = int(time.time() * 1000)
        try:
            answer = await asyncio.wait_for(future, timeout=timeout)
        # noqa 说明: py3.8 (Win7 LTS) 下 asyncio.TimeoutError 是
        # concurrent.futures.TimeoutError, 与内建 TimeoutError 不同源;
        # 必须捕获 asyncio.TimeoutError 才能在两个版本上都 default-deny。
        except asyncio.TimeoutError:  # noqa: UP041
            logger.info("审批请求超时 default-deny: request_id=%s tool=%s", req.request_id, req.tool_name)
            answer = ApprovalAnswer(approved=False, remember=False, answered_by="timeout")
        finally:
            self._pending.pop(req.request_id, None)
        # C2 (2026-09-09): 决策落库（gui 批准/拒绝 + 超时 default-deny）。
        self._record_decision(req, answer, registered_ms)
        return answer

    @staticmethod
    def _record_decision(
        req: ApprovalRequest, answer: ApprovalAnswer, registered_ms: int
    ) -> None:
        """C2 (2026-09-09): 审批决策落库，全吞降级 —— 审计是增强能力，
        绝不因持久化失败阻塞审批流。会话经 ToolExecutionContext 归因；
        run/task 经活动 dispatcher 注册表归因（子代理审批，尽力而为——
        路由侧 resolve_approval 弹出映射的时序竞争下允许归属为空）。"""
        try:
            from backend.data.approval_decision_repo import (
                ApprovalDecisionRepository,
            )

            session_id: Optional[str] = None
            run_id: Optional[str] = None
            task_id: Optional[str] = None
            try:
                from backend.tools.context import current_tool_context

                ctx = current_tool_context()
                session_id = ctx.session_id if ctx is not None else None
            except Exception:  # noqa: BLE001 — 上下文缺失降级
                session_id = None
            resolver = _approval_context_resolver
            if resolver is not None:
                try:
                    run_id, task_id = resolver(req.request_id)
                except Exception:  # noqa: BLE001 — 编排归属降级
                    run_id = task_id = None
            ApprovalDecisionRepository().append(
                tool_name=req.tool_name,
                approved=answer.approved,
                answered_by=answer.answered_by,
                request_id=req.request_id,
                session_id=session_id,
                run_id=run_id,
                task_id=task_id,
                args_summary=req.args_summary,
                risk=req.risk,
                created_at=registered_ms,
            )
        except Exception as exc:  # noqa: BLE001 — 降级铁律
            logger.debug(
                "审批决策落库失败（忽略）request=%s: %s", req.request_id, exc
            )

    def answer(self, request_id: str, approved: bool, remember: bool = False) -> bool:
        """解析一个挂起的请求。

        Returns:
            True 表示成功解析；False 表示 id 未知 / 已过期 / 已解析。
        """
        entry = self._pending.get(request_id)
        if entry is None:
            return False
        _req, future = entry
        if future.done():
            return False
        future.set_result(
            ApprovalAnswer(approved=approved, remember=remember, answered_by="gui")
        )
        return True

    def pending(self) -> List[ApprovalRequest]:
        """当前所有挂起请求（快照，按注册顺序）。"""
        return [req for req, future in self._pending.values() if not future.done()]

    def get_request(self, request_id: str) -> Optional[ApprovalRequest]:
        """按 id 查挂起请求；未知返回 None。"""
        entry = self._pending.get(request_id)
        return entry[0] if entry is not None else None

    def clear(self) -> None:
        """清空所有挂起请求（测试 / 关闭时用；未解析的 Future 保持挂起由 GC 回收）。"""
        self._pending.clear()


# ---------------------------------------------------------------------------
# 单例装配（与 backend.services.scheduler 相同模式）
# ---------------------------------------------------------------------------

_global_gate: Optional[ApprovalGate] = None


def init_permission_gate() -> ApprovalGate:
    """初始化全局 gate（main.py lifespan 启动时调用一次）。"""
    global _global_gate
    _global_gate = ApprovalGate()
    return _global_gate


def get_permission_gate() -> Optional[ApprovalGate]:
    """取全局 gate；未初始化返回 None（调用方 default-deny）。"""
    return _global_gate


def reset_permission_gate() -> None:
    """重置全局 gate（仅供测试隔离使用）。"""
    global _global_gate
    _global_gate = None


__all__ = [
    "ApprovalAnswer",
    "ApprovalRequest",
    "ApprovalGate",
    "DEFAULT_APPROVAL_TIMEOUT_S",
    "ARG_VALUE_MAX_CHARS",
    "DIFF_PREVIEW_MAX_CHARS",
    "MAX_SCRUB_DEPTH",
    "summarize_tool_args",
    "build_diff_preview",
    "init_permission_gate",
    "get_permission_gate",
    "reset_permission_gate",
]
