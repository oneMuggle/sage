"""受控浏览器控制状态（M3 控制面）。

会话级三态：

- ``agent`` —— 默认，Agent 可自由操作；
- ``paused`` —— 用户暂停，下一个浏览器动作前被门禁拦截；
- ``user_takeover`` —— 用户接管，Agent 同样被拦截。

浏览器工具在 executor 线程里执行（见 ``backend.tools.browser_tool``），而
控制路由跑在事件循环线程，因此注册表用 ``threading.Lock`` 保护；单例装配
沿用 ``backend.services.permission_gate`` 的模式，但本模块不依赖 lifespan
初始化 —— 首次访问时惰性创建，测试可用 ``reset_browser_control_for_tests``
清空状态。

路由层的 action → 状态映射：``resume`` / ``return`` → ``agent``；
``pause`` → ``paused``；``takeover`` → ``user_takeover``。
"""

from __future__ import annotations

import threading
from enum import Enum
from typing import Dict

#: 受门禁工具在错误文案里使用的两个前缀（前端/提示逻辑依赖）
PAUSED_ERROR_PREFIX = "user_paused: "
TAKEOVER_ERROR_PREFIX = "user_takeover: "


class BrowserControlState(str, Enum):
    """浏览器会话控制状态。"""

    AGENT = "agent"  # 默认：Agent 可操作
    PAUSED = "paused"  # 暂停：下一个浏览器动作前被拦
    USER_TAKEOVER = "user_takeover"  # 用户接管


#: REST 层合法 action（顺序即错误文案展示顺序）
VALID_CONTROL_ACTIONS = ("pause", "resume", "takeover", "return")

#: action → 状态
ACTION_TO_STATE = {
    "pause": BrowserControlState.PAUSED,
    "resume": BrowserControlState.AGENT,
    "takeover": BrowserControlState.USER_TAKEOVER,
    "return": BrowserControlState.AGENT,
}


class BrowserControlRegistry:
    """线程安全的会话控制状态注册表。

    未记录的 session 一律视为 ``AGENT``（查询不报错）；``reset`` 用于
    浏览器关闭后清理，等价于回到默认态。
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._states = {}  # type: Dict[str, BrowserControlState]

    def get_state(self, session_id: str) -> BrowserControlState:
        """返回会话状态；未知会话返回 ``AGENT``。"""
        with self._lock:
            return self._states.get(session_id, BrowserControlState.AGENT)

    def set_state(self, session_id: str, state: BrowserControlState) -> None:
        """写入会话状态；``AGENT`` 直接清理记录（回到默认态）。"""
        if not session_id:
            raise ValueError("session_id 不能为空")
        normalized = BrowserControlState(state)
        with self._lock:
            if normalized is BrowserControlState.AGENT:
                self._states.pop(session_id, None)
            else:
                self._states[session_id] = normalized

    def reset(self, session_id: str) -> None:
        """清除会话状态（浏览器关闭时调用）。"""
        with self._lock:
            self._states.pop(session_id, None)

    def snapshot(self) -> Dict[str, str]:
        """返回 ``session_id -> state`` 的副本（只含非默认态的会话）。"""
        with self._lock:
            return {sid: state.value for sid, state in self._states.items()}

    def clear(self) -> None:
        """清空全部状态（测试钩子）。"""
        with self._lock:
            self._states.clear()


_registry = BrowserControlRegistry()


def get_browser_control() -> BrowserControlRegistry:
    """返回进程级控制注册表单例。"""
    return _registry


def reset_browser_control_for_tests() -> None:
    """清空注册表状态（仅测试使用）。"""
    _registry.clear()
