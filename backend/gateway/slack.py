# ruff: noqa: UP006, UP007, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""Slack 消息网关（Round 16：BaseGateway 平台适配器之三）

「随身 agent」Slack 通道：Web API ``conversations.history`` 轮询
（``oldest`` ts 游标），复用 ``gateway.base.BaseGateway`` 的会话绑定 /
命令分发 / 审批转发 / LLM 对话 / 轮询线程——本模块只做 Slack 协议翻译。

安全边界（与 telegram.py 同口径）:
- 默认关闭：未配置 ``SLACK_BOT_TOKEN`` 时网关完全不启动
- 白名单：``SLACK_ALLOWED_CHANNEL_IDS``（channel 粒度，逗号分隔）之外的
  channel 一律拒答（提示一次配置方法）
- 机器人消息（``bot_id`` / 带 ``subtype``）跳过，防自环
- HTTP 全部经可注入 transport；单条 update 处理失败不中断轮询
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from backend.gateway.base import BaseGateway

logger = logging.getLogger(__name__)

SLACK_API_BASE = "https://slack.com/api"

#: Slack chat.postMessage 单条 4 万字符，但 4000 是通知可读上限口径
_MAX_MESSAGE_CHARS = 4000
#: 单频道单轮最多回放的消息数
_POLL_LIMIT = 50


class SlackTransport:
    """Slack Web API 封装（可注入/可打桩）"""

    def __init__(self, bot_token: str, api_base: str = SLACK_API_BASE) -> None:
        self._base = api_base.rstrip("/")
        self._token = bot_token

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"}

    def fetch_history(self, channel_id: str, oldest_ts: str, limit: int) -> List[Dict[str, Any]]:
        """拉某频道 ``oldest_ts``（不含）之后的消息（新→旧序）。"""
        import httpx

        resp = httpx.get(
            f"{self._base}/conversations.history",
            params={
                "channel": channel_id,
                "oldest": oldest_ts or "0",
                "limit": min(limit, 200),
            },
            headers=self._headers(),
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(f"slack api error: {data.get('error', 'unknown')}")
        return list(data.get("messages") or [])

    def post_message(self, channel_id: str, text: str) -> None:
        import httpx

        resp = httpx.post(
            f"{self._base}/chat.postMessage",
            json={"channel": channel_id, "text": text[:_MAX_MESSAGE_CHARS]},
            headers=self._headers(),
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(f"slack api error: {data.get('error', 'unknown')}")


@dataclass
class SlackConfig:
    """网关配置（双源：env 优先，settings 兜底；enabled=False 显式关闭）"""

    bot_token: str = ""
    allowed_channel_ids: List[str] = field(default_factory=list)
    poll_limit: int = _POLL_LIMIT

    @classmethod
    def load(cls) -> Optional[SlackConfig]:
        import os

        node = cls._settings_node()
        if node is not None and node.get("enabled") is False:
            return None
        token = (os.getenv("SLACK_BOT_TOKEN") or "").strip()
        raw_ids = (os.getenv("SLACK_ALLOWED_CHANNEL_IDS") or "").strip()
        if token:
            return cls(
                bot_token=token,
                allowed_channel_ids=[c.strip() for c in raw_ids.split(",") if c.strip()],
            )
        if node is None:
            return None
        token = str(node.get("bot_token") or "").strip()
        if not token:
            return None
        raw_ids = node.get("allowed_channel_ids") or []
        if isinstance(raw_ids, str):
            raw_ids = raw_ids.split(",")
        return cls(
            bot_token=token,
            allowed_channel_ids=[str(c).strip() for c in raw_ids if str(c).strip()],
        )

    @staticmethod
    def _settings_node() -> Optional[Dict[str, Any]]:
        try:
            from backend.data.settings_repo import SettingsRepository

            app_settings = SettingsRepository().get_json("app_settings")
        except Exception:  # noqa: BLE001 — 设置不可读视为未配置
            return None
        if not isinstance(app_settings, dict):
            return None
        node = app_settings.get("slack")
        return node if isinstance(node, dict) else None

    @property
    def enabled(self) -> bool:
        return bool(self.bot_token)


def _ts_sort_key(ts: str) -> float:
    """Slack ts（``1726000000.000100``）→ 可比较浮点键。"""
    try:
        return float(ts)
    except (TypeError, ValueError):
        return 0.0


def _ts_event_id(ts: str) -> int:
    """ts → 合成 int 事件 id（基类 offset 推进用；去掉小数点保序）。"""
    return int(ts.replace(".", "")) if ts.replace(".", "").isdigit() else 0


class SlackGateway(BaseGateway):
    """Slack ↔ Sage 会话网关（平台适配层）

    chat_id 即 Slack channel_id；绑定 / 命令 / 审批 / 对话全部走基类。
    """

    event_id_key = "event_ts"
    binds_table = "gateway_binds"
    new_session_title_prefix = "Slack"

    def __init__(
        self,
        config: SlackConfig,
        transport: Optional[SlackTransport] = None,
        llm_factory: Optional[Any] = None,
        db: Any = None,
    ) -> None:
        self.config = config
        self.transport = transport or SlackTransport(config.bot_token)
        #: per-channel ts 游标（该 ts 之前——含——的都拉过了）
        self._last_ts: Dict[str, str] = {}
        super().__init__(llm_factory=llm_factory, db=db)

    @property
    def allowed_chat_ids(self) -> List[str]:
        return self.config.allowed_channel_ids

    # ------------------------------------------------------------------ #
    # BaseGateway 平台能力实现
    # ------------------------------------------------------------------ #

    def fetch_updates(self) -> List[Dict[str, Any]]:
        updates: List[Dict[str, Any]] = []
        for channel_id in self.config.allowed_channel_ids:
            first_sight = channel_id not in self._last_ts
            try:
                messages = self.transport.fetch_history(
                    channel_id,
                    self._last_ts.get(channel_id, ""),
                    self.config.poll_limit,
                )
            except Exception as exc:  # noqa: BLE001 — 单频道抖动不影响其他频道
                self.stats.errors += 1
                logger.warning("Slack 拉取频道 %s 失败: %s", channel_id[:8], exc)
                continue
            # conversations.history 返回新→旧；游标取最大 ts，emit 按旧→新
            newest = self._last_ts.get(channel_id, "")
            for msg in messages:
                ts = str(msg.get("ts") or "")
                if _ts_sort_key(ts) > _ts_sort_key(newest):
                    newest = ts
            # 首见频道只推进游标、不回放历史（启动时旧消息不进对话）
            if first_sight:
                if newest:
                    self._last_ts[channel_id] = newest
                continue
            self._last_ts[channel_id] = newest
            ordered = sorted(messages, key=lambda m: _ts_sort_key(str(m.get("ts") or "")))
            for msg in ordered:
                text = (msg.get("text") or "").strip()
                # 机器人（含自己）/ 系统事件只被游标覆盖，不进对话，防自环
                if msg.get("bot_id") or msg.get("subtype"):
                    continue
                if not text:
                    continue
                updates.append(
                    {
                        "event_ts": _ts_event_id(str(msg.get("ts") or "")),
                        "channel_id": channel_id,
                        "text": text,
                    }
                )
        return updates

    def send_reply(self, chat_id: str, text: str) -> None:
        self.transport.post_message(chat_id, text)

    def parse_update(self, update: Dict[str, Any]) -> Optional[tuple]:
        channel_id = str(update.get("channel_id") or "")
        text = (update.get("text") or "").strip()
        if not channel_id or not text:
            return None
        return channel_id, text


# ------------------------------------------------------------------ #
# Global singleton
# ------------------------------------------------------------------ #

_gateway: Optional[SlackGateway] = None


def get_slack_gateway() -> Optional[SlackGateway]:
    """返回全局网关单例；未配置 token 时返回 None（网关关闭）"""
    global _gateway
    if _gateway is None:
        config = SlackConfig.load()
        if config is None:
            return None
        _gateway = SlackGateway(config)
    return _gateway


def reset_slack_gateway() -> None:
    """重置单例（测试用）"""
    global _gateway
    _gateway = None
