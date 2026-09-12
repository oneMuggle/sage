"""Telegram 消息网关 (Round 6 MVP / Round 17 平台抽象化)

「随身 agent」：在 Telegram 上远程与家里的 Sage 对话、远程审批。
平台无关能力（会话绑定 / 命令分发 / 审批转发 / LLM 对话 / 轮询线程）
在 ``gateway.base.BaseGateway``；本模块只做 Telegram 协议翻译
（getUpdates 长轮询 / sendMessage / update 信封解析）。

安全边界（MVP）:
- 默认关闭：未配置 ``TELEGRAM_BOT_TOKEN`` 时网关完全不启动
- 白名单：``TELEGRAM_ALLOWED_CHAT_IDS``（逗号分隔）之外的 chat 一律
  拒答（提示一次配置方法）
- HTTP 全部经可注入 transport；单条 update 处理失败不中断轮询
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from backend.gateway.base import (
    BaseGateway,
    GatewayStats,  # noqa: F401 — 兼容旧导入
    history_budget as _history_budget,  # noqa: F401 — 兼容旧导入
)

logger = logging.getLogger(__name__)

TELEGRAM_API_BASE = "https://api.telegram.org"

#: 单轮携带的最大历史消息数（控制 token 消耗）——基类 _MAX_HISTORY 同值
_MAX_HISTORY = 20


class TelegramTransport:
    """Telegram Bot API HTTP 封装（可注入/可打桩）"""

    def __init__(self, bot_token: str, api_base: str = TELEGRAM_API_BASE) -> None:
        self._base = f"{api_base.rstrip('/')}/bot{bot_token}"

    def get_updates(self, offset: int, timeout_seconds: int) -> List[Dict[str, Any]]:
        """长轮询一次。返回 update 列表（含 update_id 递增）。"""
        import httpx

        resp = httpx.post(
            f"{self._base}/getUpdates",
            json={"offset": offset, "timeout": timeout_seconds},
            timeout=timeout_seconds + 10,
        )
        resp.raise_for_status()
        return list(resp.json().get("result", []))

    def send_message(self, chat_id: str, text: str) -> None:
        """发送文本消息（4096 字符硬截断 —— Telegram 单条上限）。"""
        import httpx

        resp = httpx.post(
            f"{self._base}/sendMessage",
            json={"chat_id": chat_id, "text": text[:4096]},
            timeout=30,
        )
        resp.raise_for_status()


@dataclass
class TelegramConfig:
    """网关配置"""

    bot_token: str = ""
    allowed_chat_ids: List[str] = field(default_factory=list)
    poll_timeout_seconds: int = 25

    @classmethod
    def from_env(cls) -> Optional[TelegramConfig]:
        """从环境变量构造；未配置 token 时返回 None（网关关闭）。"""
        import os

        token = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
        if not token:
            return None
        raw_ids = (os.getenv("TELEGRAM_ALLOWED_CHAT_IDS") or "").strip()
        allowed = [c.strip() for c in raw_ids.split(",") if c.strip()]
        return cls(bot_token=token, allowed_chat_ids=allowed)

    @property
    def enabled(self) -> bool:
        return bool(self.bot_token)


class TelegramGateway(BaseGateway):
    """Telegram ↔ Sage 会话网关（平台适配层）

    平台无关能力（绑定存储 / 命令 / 审批转发 / 轮询 / LLM 对话）在
    ``BaseGateway``；本类只提供 Telegram transport、update 信封解析
    与白名单拒答文案。
    """

    event_id_key = "update_id"
    binds_table = "telegram_chats"
    new_session_title_prefix = "Telegram"

    def __init__(
        self,
        config: TelegramConfig,
        transport: Optional[TelegramTransport] = None,
        llm_factory: Optional[Any] = None,
        db: Any = None,
    ) -> None:
        self.config = config
        self.transport = transport or TelegramTransport(config.bot_token)
        super().__init__(llm_factory=llm_factory, db=db)

    @property
    def allowed_chat_ids(self) -> List[str]:
        return self.config.allowed_chat_ids

    # ------------------------------------------------------------------ #
    # BaseGateway 平台能力实现
    # ------------------------------------------------------------------ #

    def fetch_updates(self) -> List[Dict[str, Any]]:
        try:
            return self.transport.get_updates(
                self.offset, self.config.poll_timeout_seconds
            )
        except Exception as exc:  # noqa: BLE001 — 网络抖动下一轮再试
            self.stats.errors += 1
            logger.warning("Telegram getUpdates 失败: %s", exc)
            return []

    def send_reply(self, chat_id: str, text: str) -> None:
        self.transport.send_message(chat_id, text)

    def parse_update(self, update: Dict[str, Any]) -> Optional[tuple]:
        message = update.get("message") or {}
        chat = message.get("chat") or {}
        chat_id = str(chat.get("id", ""))
        text = (message.get("text") or "").strip()
        if not chat_id or not text:
            return None
        return chat_id, text

    # ------------------------------------------------------------------ #
    # Telegram 特有：信封解析 + 白名单拒答文案
    # ------------------------------------------------------------------ #

    def handle_update(self, update: Dict[str, Any]) -> Optional[str]:
        """处理单条 Telegram update。返回回复文本（或 None）。"""
        parsed = self.parse_update(update)
        if parsed is None:
            return None
        chat_id, text = parsed
        self.stats.updates_seen += 1

        if not self._is_allowed(chat_id):
            self.stats.rejected += 1
            logger.warning("Telegram 拒绝未授权 chat: %s", chat_id[:8])
            self._reply_text(
                chat_id,
                "此 Sage 实例未授权该对话。请在服务端配置 "
                "TELEGRAM_ALLOWED_CHAT_IDS 后重试。",
            )
            return "unauthorized"

        # 命令不进 LLM 对话（平台无关分发在基类）
        if text.startswith("/"):
            reply = self._handle_command(text, chat_id)
            if reply is not None:
                self._reply_text(chat_id, reply)
                return reply

        reply = self._chat(text, chat_id)
        self._reply_text(chat_id, reply)
        self.stats.messages_replied += 1
        return reply


# ------------------------------------------------------------------ #
# Global singleton
# ------------------------------------------------------------------ #

_gateway: Optional[TelegramGateway] = None


def get_telegram_gateway() -> Optional[TelegramGateway]:
    """返回全局网关单例；未配置 token 时返回 None（网关关闭）"""
    global _gateway
    if _gateway is None:
        config = TelegramConfig.from_env()
        if config is None:
            return None
        _gateway = TelegramGateway(config)
    return _gateway


def reset_telegram_gateway() -> None:
    """重置单例（测试用）"""
    global _gateway
    _gateway = None
