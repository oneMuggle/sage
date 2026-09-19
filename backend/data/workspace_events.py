"""工作区文件变更事件监听器（right-panel R5）。

写文件类工具（write_file / edit_file / apply_patch）成功落盘后广播
``workspace_changed`` 事件，让活跃 chat 流把变更推给前端 —— 右侧面板
变更列表事件驱动刷新 + 徽标实时化（此前只能手动刷新或重进面板）。

与 data/artifact_repo 的 ``_ARTIFACT_LISTENERS``（S7）同模式：数据层不
反向依赖 API 层，由 producer 注册/注销闭包；单进程单事件循环，list 操作
无并发问题；监听器异常一律吞掉（降级铁律：事件推送失败不能影响工具
写入结果）。
"""

from __future__ import annotations

import contextlib
from typing import Any, Callable, Dict, List

_WORKSPACE_LISTENERS: List[Callable[[Dict[str, Any]], None]] = []


def add_workspace_listener(
    fn: Callable[[Dict[str, Any]], None],
) -> Callable[[Dict[str, Any]], None]:
    """注册工作区变更事件监听器；返回 fn 便于 ``remove_workspace_listener`` 配对。"""
    _WORKSPACE_LISTENERS.append(fn)
    return fn


def remove_workspace_listener(fn: Callable[[Dict[str, Any]], None]) -> None:
    """注销工作区变更事件监听器（producer finally 必须配对调用，防闭包泄漏）。"""
    with contextlib.suppress(ValueError):
        _WORKSPACE_LISTENERS.remove(fn)


def _emit_workspace_event(event: Dict[str, Any]) -> None:
    for fn in list(_WORKSPACE_LISTENERS):
        # 降级铁律，见模块注释：单个监听器异常不阻断其余监听器与调用方
        with contextlib.suppress(Exception):
            fn(event)


def notify_workspace_changed(session_id: str, path: str, change_kind: str) -> None:
    """写文件工具成功落盘后调用；广播 ``workspace_changed`` 事件。

    Args:
        session_id: 工具上下文绑定的会话 id；为空（无上下文，如单元测试/
            后台任务）时静默跳过。
        path: 落盘文件路径（工具视角，绝对或相对均可——事件只承担
            "工作区脏了" 的刷新信号，前端刷新以 git status 全量为准）。
        change_kind: 触发工具的语义标记（"write" / "edit" / "patch"）。
    """
    if not session_id:
        return
    _emit_workspace_event(
        {
            "state": "workspace_changed",
            "session_id": session_id,
            "change": {"path": path, "kind": change_kind},
        }
    )
