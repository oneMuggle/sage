# ruff: noqa: UP006, UP007, UP035 — release/win7 Python 3.8 兼容，保留 typing 注解
"""CDP 全帧巡检：帧树枚举、隔离世界执行与全帧就绪等待。

页面内 JS 只能读取 same-origin iframe；跨域 iframe、frameset 的
``<frame>`` 与多层嵌套 frame 需要 CDP：

1. ``Page.getFrameTree`` 拿到当前页面的完整帧树（frameId / url / name）；
2. ``Page.createIsolatedWorld`` 为子 frame 建隔离世界（不受同源限制）；
3. ``Runtime.evaluate`` 带 ``contextId`` 在该 frame 的隔离世界执行采集 JS。

隔离世界与主世界共享 DOM（``data-sage-ref`` 属性跨世界可见）但 JS 全局
独立，因此 frame 内的元素定位统一走 DOM 属性，而不是 ``window`` 注册表。
安全边界由调用方负责：读取/交互前须对每个 frame 的 URL 过站点策略。
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .browser_cdp import BrowserCDPError, BrowserSession, cdp_command

logger = logging.getLogger(__name__)

#: 单次巡检最多处理的 frame 数（主 frame 也计入）。超出部分由调用方标注截断。
MAX_FRAMES = 20

#: 隔离世界名。每次快照可复用同名；世界内状态不跨调用依赖（定位走 DOM 属性）。
ISOLATED_WORLD_NAME = "sage_snapshot"

#: 全帧就绪轮询间隔（秒）
SETTLE_POLL_SECONDS = 0.3

#: 全帧就绪默认超时（秒）
SETTLE_TIMEOUT_SECONDS = 8.0

#: 连续多少轮「已就绪 + 文本长度不变」视为稳定
SETTLE_STABLE_ROUNDS = 2

#: frame 探活表达式：readyState + 正文长度（隔离世界可读 DOM）
_PROBE_EXPRESSION = (
    "(function(){return JSON.stringify({"
    "ready:(document.readyState||''),"
    "text_len:((document.body&&document.body.innerText)||'').length"
    "});})()"
)


@dataclass(frozen=True)
class FrameInfo:
    """单个 frame 的静态信息。"""

    frame_id: str
    parent_id: str
    url: str
    name: str
    is_main: bool


def flatten_frame_tree(tree: Dict[str, Any]) -> List[FrameInfo]:
    """把 ``Page.getFrameTree`` 的返回递归展平成列表（主 frame 在首位）。

    接受两种输入：完整返回 ``{"frameTree": {...}}`` 或内层 tree
    ``{"frame": {...}, "childFrames": [...]}``。结构异常返回空列表。
    """
    if not isinstance(tree, dict):
        return []
    root = tree.get("frameTree") if isinstance(tree.get("frameTree"), dict) else tree
    if not isinstance(root, dict):
        return []

    frames: List[FrameInfo] = []

    def walk(node: Any) -> None:
        if not isinstance(node, dict):
            return
        frame = node.get("frame")
        if isinstance(frame, dict):
            frame_id = str(frame.get("id") or "")
            if frame_id:
                frames.append(
                    FrameInfo(
                        frame_id=frame_id,
                        parent_id=str(frame.get("parentId") or ""),
                        url=str(frame.get("url") or ""),
                        name=str(frame.get("name") or ""),
                        is_main=not frames,
                    )
                )
        children = node.get("childFrames")
        if isinstance(children, list):
            for child in children:
                walk(child)

    walk(root)
    return frames


def list_frames(
    session: BrowserSession, target_id: Optional[str] = None
) -> List[FrameInfo]:
    """枚举当前页面目标的所有 frame（含 frameset 与跨域 frame）。

    失败抛 ``BrowserCDPError``，由调用方决定降级（例如回退页面内 JS 遍历）。
    """
    cdp_command(session, "Page.enable", {}, target_id=target_id)
    result = cdp_command(session, "Page.getFrameTree", {}, target_id=target_id)
    if not isinstance(result, dict) or not result.get("frameTree"):
        raise BrowserCDPError("Page.getFrameTree 返回异常")
    return flatten_frame_tree(result)


def create_world(
    session: BrowserSession, frame_id: str, target_id: Optional[str] = None
) -> int:
    """在指定 frame 创建隔离世界，返回 ``executionContextId``。"""
    result = cdp_command(
        session,
        "Page.createIsolatedWorld",
        {"frameId": frame_id, "worldName": ISOLATED_WORLD_NAME},
        target_id=target_id,
    )
    try:
        context_id = int((result or {}).get("executionContextId") or 0)
    except (TypeError, ValueError) as exc:
        raise BrowserCDPError("Page.createIsolatedWorld 返回的 contextId 非整数") from exc
    if context_id <= 0:
        raise BrowserCDPError("Page.createIsolatedWorld 未返回 executionContextId")
    return context_id


def _evaluate_json_raw(
    session: BrowserSession,
    expression: str,
    target_id: Optional[str] = None,
    context_id: Optional[int] = None,
) -> Any:
    """Runtime.evaluate（returnByValue）→ value；页面异常抛 BrowserCDPError。"""
    params: Dict[str, Any] = {"expression": expression, "returnByValue": True}
    if context_id is not None:
        params["contextId"] = int(context_id)
    result = cdp_command(session, "Runtime.evaluate", params, target_id=target_id)
    details = result.get("exceptionDetails")
    if details:
        raise BrowserCDPError(f"frame 脚本执行失败: {json.dumps(details)[:300]}")
    return (result.get("result") or {}).get("value")


def evaluate_in_context(
    session: BrowserSession,
    expression: str,
    context_id: int,
    target_id: Optional[str] = None,
) -> Any:
    """在指定隔离世界执行表达式（跨域 frame 也适用）。"""
    return _evaluate_json_raw(session, expression, target_id=target_id, context_id=context_id)


def build_probe_expression() -> str:
    """frame 就绪探活 JS（readyState + 正文长度）。"""
    return _PROBE_EXPRESSION


def _parse_probe(value: Any) -> Dict[str, Any]:
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except ValueError:
            parsed = None
        if isinstance(parsed, dict):
            value = parsed
    if not isinstance(value, dict):
        return {"ready": "", "text_len": 0}
    return {
        "ready": str(value.get("ready") or ""),
        "text_len": int(value.get("text_len") or 0),
    }


def probe_frame(
    session: BrowserSession,
    frame: FrameInfo,
    target_id: Optional[str] = None,
    context_id: Optional[int] = None,
) -> Dict[str, Any]:
    """读取单个 frame 的就绪状态与正文长度。

    主 frame 用默认上下文；子 frame 用隔离世界（``context_id`` 可由调用方
    缓存复用）。失败返回 ``{"ready": "", "text_len": 0, "error": True}``，
    不抛错——调用方按「未就绪」处理，下一轮重建世界。
    """
    try:
        if frame.is_main:
            value = _evaluate_json_raw(session, _PROBE_EXPRESSION, target_id=target_id)
        else:
            resolved = (
                context_id
                if context_id is not None
                else create_world(session, frame.frame_id, target_id=target_id)
            )
            value = evaluate_in_context(
                session, _PROBE_EXPRESSION, resolved, target_id=target_id
            )
    except BrowserCDPError as exc:
        logger.debug("frame 探活失败 frame=%s: %s", frame.frame_id, exc)
        return {"frame_id": frame.frame_id, "ready": "", "text_len": 0, "error": True}
    probe = _parse_probe(value)
    probe["frame_id"] = frame.frame_id
    return probe


def all_frames_settled(probes: List[Dict[str, Any]]) -> bool:
    """所有 frame 的 ``readyState`` 都已进入 interactive/complete。"""
    if not probes:
        return True
    for probe in probes:
        if str(probe.get("ready") or "") not in ("interactive", "complete"):
            return False
    return True


def wait_frames_settled(
    session: BrowserSession,
    target_id: Optional[str] = None,
    timeout: float = SETTLE_TIMEOUT_SECONDS,
    frames: Optional[List[FrameInfo]] = None,
) -> bool:
    """等待所有 frame 就绪且正文长度连续 ``SETTLE_STABLE_ROUNDS`` 轮不变。

    frame 上下文随导航销毁时探活失败，按未就绪处理并在下一轮重建世界。
    超时返回 False（不抛错，调用方继续后续逻辑）。
    """
    if frames is None:
        try:
            frames = list_frames(session, target_id)
        except BrowserCDPError as exc:
            logger.debug("全帧等待降级：frame tree 不可用: %s", exc)
            return False
    if not frames:
        return True

    deadline = time.monotonic() + max(0.0, float(timeout))
    contexts: Dict[str, int] = {}
    last_lengths: Optional[List[int]] = None
    stable_rounds = 0
    while True:
        probes = [
            probe_frame(
                session,
                frame,
                target_id=target_id,
                context_id=contexts.get(frame.frame_id),
            )
            for frame in frames
        ]
        for frame, probe in zip(frames, probes):
            if probe.get("error") and not frame.is_main:
                contexts.pop(frame.frame_id, None)
        lengths = [int(probe.get("text_len") or 0) for probe in probes]
        if all_frames_settled(probes) and lengths == last_lengths:
            stable_rounds += 1
            if stable_rounds >= SETTLE_STABLE_ROUNDS:
                return True
        else:
            stable_rounds = 0
        last_lengths = lengths
        if time.monotonic() >= deadline:
            return False
        time.sleep(SETTLE_POLL_SECONDS)


__all__ = [
    "FrameInfo",
    "ISOLATED_WORLD_NAME",
    "MAX_FRAMES",
    "SETTLE_POLL_SECONDS",
    "SETTLE_STABLE_ROUNDS",
    "SETTLE_TIMEOUT_SECONDS",
    "all_frames_settled",
    "build_probe_expression",
    "create_world",
    "evaluate_in_context",
    "flatten_frame_tree",
    "list_frames",
    "probe_frame",
    "wait_frames_settled",
]
