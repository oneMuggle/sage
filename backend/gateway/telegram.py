"""Telegram 消息网关 MVP (Round 6, 对标 hermes-agent gateway)

「随身 agent」：在 Telegram 上远程与家里的 Sage 对话。复用既有后端
基建（SessionRepository/MessageRepository/LLM 工厂），本模块只做平台
适配：长轮询收消息 → 白名单 → 会话绑定 → LLM 单轮 → sendMessage。

安全边界（MVP）:
- 默认关闭：未配置 ``TELEGRAM_BOT_TOKEN`` 时网关完全不启动
- 白名单：``TELEGRAM_ALLOWED_CHAT_IDS``（逗号分隔）之外的 chat 一律
  拒答（提示一次配置方法）
- HTTP 全部经可注入 transport；单条 update 处理失败不中断轮询
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

TELEGRAM_API_BASE = "https://api.telegram.org"

#: 单轮携带的最大历史消息数（控制 token 消耗）
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
class GatewayStats:
    """网关运行统计（status 端点用）"""

    updates_seen: int = 0
    messages_replied: int = 0
    rejected: int = 0
    errors: int = 0


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


class TelegramGateway:
    """Telegram ↔ Sage 会话网关

    chat_id ↔ session_id 绑定持久化在 ``telegram_chats`` 表：
    首条消息建新会话，后续消息续聊同一会话（跨会话历史由
    MessageRepository 提供）。
    """

    def __init__(
        self,
        config: TelegramConfig,
        transport: Optional[TelegramTransport] = None,
        llm_factory: Optional[Any] = None,
        db: Any = None,
    ) -> None:
        self.config = config
        self.transport = transport or TelegramTransport(config.bot_token)
        self._llm_factory = llm_factory  # (session_id) -> LLMClient；None=惰性
        self.db = db
        self.offset = 0
        self.stats = GatewayStats()
        # Round 10: 已转发审批的去重集合（request_id 全量；进程内即可）
        self._forwarded_approval_ids: set = set()
        self._ensure_table()

    # ------------------------------------------------------------------ #
    # 绑定存储
    # ------------------------------------------------------------------ #

    def _conn(self):
        if self.db is None:
            from backend.data.database import get_database

            self.db = get_database()
        return self.db.get_connection()

    def _ensure_table(self) -> None:
        try:
            self._conn().execute(
                """
                CREATE TABLE IF NOT EXISTS telegram_chats (
                    chat_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    created_at INTEGER NOT NULL
                )
                """
            )
            self._conn().commit()
        except Exception as exc:  # noqa: BLE001 — 绑定表失败不拖垮进程
            logger.warning("telegram_chats 建表失败: %s", exc)

    def _session_for_chat(self, chat_id: str) -> str:
        """取 chat 的绑定会话；无则建新会话并绑定"""
        row = self._conn().execute(
            "SELECT session_id FROM telegram_chats WHERE chat_id = ?",
            (chat_id,),
        ).fetchone()
        if row:
            return row[0]
        from backend.data.session_repo import SessionRepository

        session = SessionRepository().create(title=f"Telegram {chat_id}")
        self._conn().execute(
            "INSERT INTO telegram_chats (chat_id, session_id, created_at) "
            "VALUES (?, ?, ?)",
            (chat_id, session.id, int(time.time() * 1000)),
        )
        self._conn().commit()
        return session.id

    # ------------------------------------------------------------------ #
    # 消息处理
    # ------------------------------------------------------------------ #

    def _is_allowed(self, chat_id: str) -> bool:
        return chat_id in set(self.config.allowed_chat_ids)

    def _reply_text(self, chat_id: str, text: str) -> None:
        self.transport.send_message(chat_id, text)

    def handle_update(self, update: Dict[str, Any]) -> Optional[str]:
        """处理单条 Telegram update。返回回复文本（或 None）。"""
        message = update.get("message") or {}
        chat = message.get("chat") or {}
        chat_id = str(chat.get("id", ""))
        text = (message.get("text") or "").strip()
        if not chat_id or not text:
            return None
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

        # Round 10: 审批命令（/approve /deny /pending）—— 远程批准 agent
        # 的危险操作，网关真正可用于无人值守场景。命令不进 LLM 对话。
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
    # Round 10: 审批转发与命令
    # ------------------------------------------------------------------ #

    @staticmethod
    def _short_id(request_id: str) -> str:
        """request_id 前 8 位（审批命令用短 id）"""
        return request_id.replace("-", "")[:8]

    def _resolve_pending(self, short_id: str) -> Optional[Any]:
        """按短 id 前缀匹配挂起审批请求"""
        from backend.services.permission_gate import get_permission_gate

        gate = get_permission_gate()
        if gate is None:
            return None
        for req in gate.pending():
            if self._short_id(req.request_id) == short_id:
                return req
        return None

    def _handle_command(  # noqa: PLR0911 — 命令分发逐条 return 可读性更好
        self, text: str, chat_id: str
    ) -> Optional[str]:
        """处理 /approve /deny /pending /status 命令。

        Returns:
            回复文本；非命令（None）则继续走 LLM 对话。
        """
        from backend.services.permission_gate import get_permission_gate

        parts = text.split()
        cmd = parts[0].lower()

        if cmd in ("/approve", "/deny"):
            if len(parts) < 2:
                return f"用法: {cmd} <短id>（见 /pending 列表）"
            req = self._resolve_pending(parts[1])
            if req is None:
                return f"未找到挂起审批 {parts[1]}"
            gate = get_permission_gate()
            if gate is None or not gate.answer(req.request_id, approved=cmd == "/approve"):
                return f"审批 {parts[1]} 已失效或已处理"
            verb = "已批准" if cmd == "/approve" else "已拒绝"
            logger.info("Telegram 审批: %s %s (by chat %s)", verb, req.request_id, chat_id[:8])
            return f"{verb} {req.tool_name} [{self._short_id(req.request_id)}]"

        if cmd == "/pending":
            gate = get_permission_gate()
            pending = gate.pending() if gate is not None else []
            if not pending:
                return "当前没有待审批请求。"
            lines = [
                f"[{self._short_id(r.request_id)}] {r.tool_name} — {r.risk}"
                for r in pending
            ]
            return "待审批:\n" + "\n".join(lines)

        if cmd == "/status":
            return (
                f"Sage 网关运行中。统计: 收到 {self.stats.updates_seen} / "
                f"回复 {self.stats.messages_replied} / 拒绝 {self.stats.rejected}"
            )

        return None  # 非网关命令 → 交给 LLM 对话

    def _forward_new_approvals(self) -> int:
        """把新的挂起审批转发到白名单 chats（每 tick 调用，已转发去重）"""
        from backend.services.permission_gate import get_permission_gate

        gate = get_permission_gate()
        if gate is None:
            return 0
        forwarded = 0
        for req in gate.pending():
            if req.request_id in self._forwarded_approval_ids:
                continue
            self._forwarded_approval_ids.add(req.request_id)
            body = (
                f"🔐 待审批 [{self._short_id(req.request_id)}]\n"
                f"工具: {req.tool_name}\n风险: {req.risk}\n"
                f"原因: {req.message}\n参数: {req.args_summary}\n\n"
                f"回复 /approve {self._short_id(req.request_id)} 批准，"
                f"/deny {self._short_id(req.request_id)} 拒绝"
            )
            for chat_id in self.config.allowed_chat_ids:
                try:
                    self._reply_text(chat_id, body)
                    forwarded += 1
                except Exception as exc:  # noqa: BLE001 — 单 chat 失败不中断
                    logger.warning("审批转发失败 (chat=%s): %s", chat_id[:8], exc)
        return forwarded

    def _chat(self, text: str, chat_id: str) -> str:
        """会话绑定 + 历史拼装 + LLM 单轮 + 消息落库"""
        from backend.data.session_repo import Message, MessageRepository

        session_id = self._session_for_chat(chat_id)
        repo = MessageRepository()

        user_msg = Message(
            id=f"msg-{uuid.uuid4().hex[:12]}",
            session_id=session_id,
            role="user",
            content=text,
            created_at=int(time.time() * 1000) // 1000,
        )
        repo.save(user_msg)
        history = repo.get_by_session(session_id, limit=_MAX_HISTORY)

        client = self._resolve_llm(session_id)
        if client is None:
            reply = "（Sage 未配置可用的 LLM 端点，请在设置页配置后再试。）"
        else:
            import asyncio

            messages = [{"role": m.role, "content": m.content} for m in history]
            try:
                response = asyncio.run(client.chat(messages))
                reply = (response.content or "").strip() or "（空响应，请重试。）"
            except Exception as exc:  # noqa: BLE001 — LLM 故障降级为错误提示
                logger.warning("Telegram LLM 调用失败: %s", exc)
                reply = f"（Sage 处理失败: {exc}）"

        assistant_msg = Message(
            id=f"msg-{uuid.uuid4().hex[:12]}",
            session_id=session_id,
            role="assistant",
            content=reply,
            created_at=int(time.time() * 1000) // 1000,
        )
        repo.save(assistant_msg)
        return reply

    def _resolve_llm(self, session_id: str) -> Optional[Any]:
        """解析 LLM 客户端（注入优先，settings 兜底；不可用返回 None）"""
        if self._llm_factory is not None:
            return self._llm_factory(session_id)
        try:
            from backend.core.legacy.llm_client import LLMClient, LLMConfig
            from backend.orchestration.llm_factory import load_llm_config_for_chat

            cfg = load_llm_config_for_chat(session_id=session_id)
            if cfg is None:
                return None
            return LLMClient(LLMConfig(**cfg))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Telegram LLM 解析失败: %s", exc)
            return None

    # ------------------------------------------------------------------ #
    # 轮询
    # ------------------------------------------------------------------ #

    def poll_once(self) -> int:
        """长轮询一次并逐条处理。返回处理的 update 数（崩溃安全续传）。"""
        try:
            updates = self.transport.get_updates(
                self.offset, self.config.poll_timeout_seconds
            )
        except Exception as exc:  # noqa: BLE001 — 网络抖动下一轮再试
            self.stats.errors += 1
            logger.warning("Telegram getUpdates 失败: %s", exc)
            return 0
        for update in updates:
            self.offset = max(self.offset, int(update.get("update_id", 0)) + 1)
            try:
                self.handle_update(update)
            except Exception as exc:  # noqa: BLE001 — 单条失败不中断轮询
                self.stats.errors += 1
                logger.warning("Telegram update 处理失败: %s", exc)
        # Round 10: 转发新的挂起审批到白名单 chats
        try:
            self._forward_new_approvals()
        except Exception as exc:  # noqa: BLE001 — 转发失败不中断轮询
            logger.warning("审批转发失败: %s", exc)
        return len(updates)

    def start_polling(self, poll_interval_seconds: float = 3.0) -> None:
        """启动后台长轮询守护线程（幂等）"""
        import threading

        if getattr(self, "_poll_thread", None) and self._poll_thread.is_alive():
            return
        self._running = True

        def _loop() -> None:
            while self._running:
                try:
                    self.poll_once()
                except Exception as exc:  # noqa: BLE001 — 循环必须存活
                    logger.warning("Telegram 轮询循环异常: %s", exc)
                time.sleep(poll_interval_seconds)

        self._poll_thread = threading.Thread(
            target=_loop, name="telegram-gateway-poll", daemon=True
        )
        self._poll_thread.start()
        logger.info("Telegram 轮询线程已启动")

    def stop_polling(self) -> None:
        """停止轮询线程（线程为 daemon，进程退出亦可兜底）"""
        self._running = False


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
