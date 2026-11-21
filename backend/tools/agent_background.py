"""M2: ``agent(background=True)`` —— 后台子代理调度与完成通知。

从 ``AgentTool`` 拆出（保持 agent_tool.py < 800 行棘轮）：

- 后台任务登记（``_BACKGROUND_TASKS``）与每 stream 在飞计数；
- 完成/失败/取消时经主 agent 的 ``inject_system_note`` 把结果注入下一
  迭代边界（不落库、不发 STEER_CONSUMED）；
- 主 agent 默认从活跃聊天流注册表（``chat_stream_state._ACTIVE_STREAMS``）
  解析，测试可注入 resolver。
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any, Dict, Optional

from backend.tools.base import ToolResult

logger = logging.getLogger(__name__)

#: 每 stream 同时在跑的后台子代理上限（防主代理一轮派发过多）。
MAX_BACKGROUND_AGENTS_PER_STREAM = 4

#: 后台子代理任务登记（handle_id → asyncio.Task）。
_BACKGROUND_TASKS: Dict[str, asyncio.Task[Any]] = {}
#: 每 stream 的后台子代理在飞计数。
_BACKGROUND_COUNTS: Dict[str, int] = {}


def resolve_main_agent(resolver: Any, stream_id: Optional[str]) -> Any:
    """定位主 agent（用于回传完成通知）。默认经活跃聊天流注册表查找。"""
    if resolver is not None:
        return resolver(stream_id)
    if not stream_id:
        return None
    try:
        from backend.api.chat_stream_state import _ACTIVE_STREAMS

        entry = _ACTIVE_STREAMS.get(stream_id)
        return entry.get("agent") if isinstance(entry, dict) else None
    except Exception:  # noqa: BLE001 — 注册表不可用按"无主 agent"处理
        return None


def _notify_main_agent(main_agent: Any, note: str) -> None:
    try:
        inject = getattr(main_agent, "inject_system_note", None)
        if callable(inject):
            inject(note)
    except Exception:  # noqa: BLE001 — 通知失败绝不影响任务收尾
        logger.debug("后台子代理完成通知注入失败", exc_info=True)


async def start_background(
    *,
    tool: Any,
    resolver: Any,
    description: str,
    prompt: str,
    subagent_type: Optional[str],
) -> ToolResult:
    """登记并启动后台子代理，立即返回 running 句柄。"""
    from backend.tools.context import current_tool_context

    ctx = current_tool_context()
    stream_id = ctx.stream_id if ctx is not None else None
    main_agent = resolve_main_agent(resolver, stream_id)
    if not stream_id or main_agent is None:
        return ToolResult(
            success=False,
            error=(
                "background_requires_stream: 后台子代理需要活跃的聊天流"
                "（无法定位主 agent 以回传结果）"
            ),
        )
    running = _BACKGROUND_COUNTS.get(stream_id, 0)
    if running >= MAX_BACKGROUND_AGENTS_PER_STREAM:
        return ToolResult(
            success=False,
            error=f"background_agent_limit (limit={MAX_BACKGROUND_AGENTS_PER_STREAM})",
        )
    _BACKGROUND_COUNTS[stream_id] = running + 1
    handle_id = f"bg-{uuid.uuid4().hex[:12]}"
    task = asyncio.create_task(
        _run_background(tool, handle_id, stream_id, description, prompt, subagent_type, main_agent)
    )
    _BACKGROUND_TASKS[handle_id] = task
    logger.info(
        "后台子代理已派发 handle=%s stream=%s running=%d",
        handle_id,
        stream_id,
        running + 1,
    )
    return ToolResult(
        success=True,
        content={
            "status": "running",
            "handle_id": handle_id,
            "description": description,
            "message": (
                "子代理已在后台运行；完成后会以【后台子代理完成】通知你，"
                "期间可以继续其他工作。"
            ),
        },
    )


async def _run_background(
    tool: Any,
    handle_id: str,
    stream_id: str,
    description: str,
    prompt: str,
    subagent_type: Optional[str],
    main_agent: Any,
) -> None:
    try:
        result = await tool.execute_async(
            description=description,
            prompt=prompt,
            subagent_type=subagent_type,
            background=False,
        )
    except asyncio.CancelledError:
        _notify_main_agent(main_agent, f"【后台子代理已取消】任务：{description}")
        raise
    except Exception as exc:  # noqa: BLE001 — 后台崩溃转通知，不冒泡
        logger.exception("后台子代理崩溃 handle=%s", handle_id)
        _notify_main_agent(
            main_agent, f"【后台子代理失败】任务：{description}\n错误：{exc}"
        )
        return
    finally:
        _BACKGROUND_TASKS.pop(handle_id, None)
        left = _BACKGROUND_COUNTS.get(stream_id, 1) - 1
        if left > 0:
            _BACKGROUND_COUNTS[stream_id] = left
        else:
            _BACKGROUND_COUNTS.pop(stream_id, None)

    if result.success:
        payload = result.content if isinstance(result.content, dict) else {}
        answer = payload.get("answer", result.content)
        _notify_main_agent(
            main_agent,
            f"【后台子代理完成】任务：{description}\n结果：{str(answer)[:2000]}",
        )
    else:
        _notify_main_agent(
            main_agent,
            f"【后台子代理失败】任务：{description}\n错误：{result.error or 'unknown'}",
        )
