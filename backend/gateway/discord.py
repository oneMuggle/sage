# ruff: noqa: UP006, UP007, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""Discord 消息网关（Round 16：BaseGateway 平台适配器之二）

「随身 agent」Discord 通道：REST 轮询频道消息（snowflake 游标单调递增），
复用 ``gateway.base.BaseGateway`` 的会话绑定 / 命令分发 / 审批转发 /
LLM 对话 / 轮询线程——本模块只做 Discord 协议翻译。

安全边界（与 telegram.py 同口径）:
- 默认关闭：未配置 ``DISCORD_BOT_TOKEN`` 时网关完全不启动
- 白名单：``DISCORD_ALLOWED_CHANNEL_IDS``（channel 粒度，逗号分隔）之外的
  channel 一律拒答（提示一次配置方法）
- 机器人自身消息（``author.bot``）跳过，防自环
- HTTP 全部经可注入 transport；单条 update 处理失败不中断轮询
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from backend.gateway.base import BaseGateway

logger = logging.getLogger(__name__)

DISCORD_API_BASE = "https://discord.com/api/v10"

#: Discord 单条消息 2000 字符硬上限
_MAX_MESSAGE_CHARS = 2000
#: 单频道单轮最多回放的消息数
_POLL_LIMIT = 50


class DiscordTransport:
    """Discord REST 封装（可注入/可打桩）"""

    def __init__(self, bot_token: str, api_base: str = DISCORD_API_BASE) -> None:
        self._base = api_base.rstrip("/")
        self._token = bot_token

    def fetch_messages(self, channel_id: str, after_id: str, limit: int) -> List[Dict[str, Any]]:
        """拉某频道 ``after_id``（snowflake）之后的消息（旧→新序）。"""
        import httpx

        resp = httpx.get(
            f"{self._base}/channels/{channel_id}/messages",
            params={"after": after_id or "0", "limit": min(limit, 100)},
            headers={"Authorization": f"Bot {self._token}"},
            timeout=30,
        )
        resp.raise_for_status()
        # Discord 返回新→旧，统一翻成旧→新供游标推进
        return list(reversed(resp.json()))

    def send_message(self, channel_id: str, text: str) -> None:
        import httpx

        resp = httpx.post(
            f"{self._base}/channels/{channel_id}/messages",
            json={"content": text[:_MAX_MESSAGE_CHARS]},
            headers={"Authorization": f"Bot {self._token}"},
            timeout=30,
        )
        resp.raise_for_status()


@dataclass
class DiscordConfig:
    """网关配置（双源：env 优先，settings 兜底；enabled=False 显式关闭）"""

    bot_token: str = ""
    allowed_channel_ids: List[str] = field(default_factory=list)
    poll_limit: int = _POLL_LIMIT

    @classmethod
    def load(cls) -> Optional[DiscordConfig]:
        import os

        node = cls._settings_node()
        if node is not None and node.get("enabled") is False:
            return None
        token = (os.getenv("DISCORD_BOT_TOKEN") or "").strip()
        raw_ids = (os.getenv("DISCORD_ALLOWED_CHANNEL_IDS") or "").strip()
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
        node = app_settings.get("discord")
        return node if isinstance(node, dict) else None

    @property
    def enabled(self) -> bool:
        return bool(self.bot_token)


class DiscordGateway(BaseGateway):
    """Discord ↔ Sage 会话网关（平台适配层）

    chat_id 即 Discord channel_id；绑定 / 命令 / 审批 / 对话全部走基类。
    """

    event_id_key = "message_id"
    binds_table = "gateway_binds"
    new_session_title_prefix = "Discord"

    def __init__(
        self,
        config: DiscordConfig,
        transport: Optional[DiscordTransport] = None,
        llm_factory: Optional[Any] = None,
        db: Any = None,
    ) -> None:
        self.config = config
        self.transport = transport or DiscordTransport(config.bot_token)
        #: per-channel snowflake 游标（该 id 之前——含——的都拉过了）
        self._last_message_id: Dict[str, str] = {}
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
            first_sight = channel_id not in self._last_message_id
            try:
                messages = self.transport.fetch_messages(
                    channel_id,
                    self._last_message_id.get(channel_id, ""),
                    self.config.poll_limit,
                )
            except Exception as exc:  # noqa: BLE001 — 单频道抖动不影响其他频道
                self.stats.errors += 1
                logger.warning("Discord 拉取频道 %s 失败: %s", channel_id[:8], exc)
                continue
            # 首见频道只推进游标、不回放历史（启动时旧消息不进对话）
            newest_id = str(messages[-1].get("id") or "") if messages else ""
            if first_sight:
                if newest_id:
                    self._last_message_id[channel_id] = newest_id
                continue
            for msg in messages:
                msg_id = str(msg.get("id") or "")
                if msg_id:
                    self._last_message_id[channel_id] = msg_id
                # 机器人（含自己）消息只推进游标、不进对话，防自环
                author = msg.get("author") or {}
                if author.get("bot"):
                    continue
                content = (msg.get("content") or "").strip()
                if not msg_id or not content:
                    continue
                updates.append(
                    {
                        "message_id": int(msg_id),  # snowflake 原生 int 可单调推进 offset
                        "channel_id": channel_id,
                        "author": author,
                        "content": content,
                    }
                )
        return updates

    def send_reply(self, chat_id: str, text: str) -> None:
        self.transport.send_message(chat_id, text)

    def parse_update(self, update: Dict[str, Any]) -> Optional[tuple]:
        channel_id = str(update.get("channel_id") or "")
        text = (update.get("content") or "").strip()
        if not channel_id or not text:
            return None
        return channel_id, text


# ------------------------------------------------------------------ #
# Global singleton
# ------------------------------------------------------------------ #

_gateway: Optional[DiscordGateway] = None


def get_discord_gateway() -> Optional[DiscordGateway]:
    """返回全局网关单例；未配置 token 时返回 None（网关关闭）"""
    global _gateway
    if _gateway is None:
        config = DiscordConfig.load()
        if config is None:
            return None
        _gateway = DiscordGateway(config)
    return _gateway


def reset_discord_gateway() -> None:
    """重置单例（测试用）"""
    global _gateway
    _gateway = None
