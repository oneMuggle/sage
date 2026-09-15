"""Gateway Base - 网关多平台抽象基类 (Round 17, 对标 hermes platform adapters)

把「Sage 会话绑定 / 命令分发 / 审批转发 / LLM 对话 / 轮询线程」这些
平台无关能力收敛到 BaseGateway；新平台（Discord/Slack…）只需实现：

- ``fetch_updates()``  —— 拉取平台原始事件（含稳定递增的事件 id 字段）
- ``send_reply(chat_id, text)`` —— 发送文本
- ``parse_update(update)`` —— 信封解析为 (chat_id, text)
- ``allowed_chat_ids`` —— 白名单

参照 hermes 的 platform adapters：平台层只做协议翻译，Sage 语义
（会话绑定 / 审批 / 历史）全部在基类。
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_MAX_HISTORY = 20


@dataclass
class GatewayStats:
    """网关运行统计（status 端点用）"""

    updates_seen: int = 0
    messages_replied: int = 0
    rejected: int = 0
    errors: int = 0


def history_budget(history: List[Any]) -> tuple:
    """按 token 预算截断网关对话历史（Round 11）。

    从最新往回累积估算 token（复用 context_first_aid 估算器），超出
    ``SAGE_GW_HISTORY_TOKEN_BUDGET``（默认 4000，<=0 关闭仅条数上限）即停，
    至少保留最近 2 条。

    Returns:
        (kept_messages, omitted_count)
    """
    import os

    if not history:
        return history, 0
    try:
        budget = int(os.getenv("SAGE_GW_HISTORY_TOKEN_BUDGET", "4000"))
    except ValueError:
        budget = 4000
    if budget <= 0:
        return history, 0

    from backend.core.legacy.context_first_aid import estimate_messages_tokens

    kept: List[Any] = []
    for msg in reversed(history):
        candidate = [
            {
                "role": getattr(msg, "role", "user"),
                "content": getattr(msg, "content", ""),
            }
        ] + [{"role": m.role, "content": m.content} for m in reversed(kept)]
        if kept and estimate_messages_tokens(candidate) > budget:
            break
        kept.append(msg)
    kept.reverse()
    if len(kept) < 2 and len(history) >= 2:
        kept = list(history[-2:])
    omitted = len(history) - len(kept)
    return kept, omitted


class BaseGateway:
    """平台无关网关基类

    子类契约：
    - ``fetch_updates()``: 拉取新事件列表（dict 含 ``event_id_key`` 递增 id）
    - ``send_reply(chat_id, text)``: 发文本（子类自行截断到平台上限）
    - ``parse_update(update)``: 信封 → (chat_id, text) 或 None
    - ``allowed_chat_ids``: 白名单（属性/property）
    - ``binds_table`` / ``new_session_title_prefix``: 绑定存储参数
    """

    #: 平台事件 id 字段名（轮询 offset 推进用）
    event_id_key = "update_id"
    #: 绑定表名（Telegram 沿用 telegram_chats；新平台用 gateway_binds）
    binds_table = "gateway_binds"
    #: 新建会话标题前缀
    new_session_title_prefix = "Gateway"

    def __init__(
        self,
        llm_factory: Optional[Any] = None,
        db: Any = None,
    ) -> None:
        self._llm_factory = llm_factory  # (session_id) -> LLMClient；None=惰性
        self.db = db
        self.offset = 0
        self.stats = GatewayStats()
        # 已转发审批的去重集合（request_id 全量；进程内即可）
        self._forwarded_approval_ids: set = set()
        self._poll_thread: Optional[threading.Thread] = None
        self._running = False
        self._ensure_table()

    # 子类必须提供的平台能力 ----------------------------------------------

    def fetch_updates(self) -> List[Dict[str, Any]]:
        raise NotImplementedError

    def send_reply(self, chat_id: str, text: str) -> None:
        raise NotImplementedError

    def parse_update(self, update: Dict[str, Any]) -> Optional[Tuple[str, str]]:
        raise NotImplementedError

    def handle_update(self, update: Dict[str, Any]) -> Optional[str]:
        """默认编排：parse → 统计 → process_message（子类可覆写加平台分支）"""
        parsed = self.parse_update(update)
        if parsed is None:
            return None
        chat_id, text = parsed
        self.stats.updates_seen += 1
        return self.process_message(chat_id, text)

    @property
    def allowed_chat_ids(self) -> List[str]:
        raise NotImplementedError

    # ------------------------------------------------------------------ #
    # 绑定存储（平台无关）
    # ------------------------------------------------------------------ #

    def _conn(self):
        if self.db is None:
            from backend.data.database import get_database

            self.db = get_database()
        return self.db.get_connection()

    def _ensure_table(self) -> None:
        try:
            self._conn().execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self.binds_table} (
                    chat_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    created_at INTEGER NOT NULL
                )
                """
            )
            self._conn().commit()
        except Exception as exc:  # noqa: BLE001 — 绑定表失败不拖垮进程
            logger.warning("%s 建表失败: %s", self.binds_table, exc)

    def _session_for_chat(self, chat_id: str) -> str:
        """取 chat 的绑定会话；无则建新会话并绑定"""
        row = self._conn().execute(
            f"SELECT session_id FROM {self.binds_table} WHERE chat_id = ?",
            (chat_id,),
        ).fetchone()
        if row:
            return row[0]
        from backend.data.session_repo import SessionRepository

        session = SessionRepository().create(
            title=f"{self.new_session_title_prefix} {chat_id}"
        )
        self._conn().execute(
            f"INSERT INTO {self.binds_table} (chat_id, session_id, created_at) "
            "VALUES (?, ?, ?)",
            (chat_id, session.id, int(time.time() * 1000)),
        )
        self._conn().commit()
        return session.id

    def unbind_chat(self, chat_id: str) -> bool:
        """解绑 chat（下次消息重新建会话）。返回是否有绑定被删除。"""
        cursor = self._conn().execute(
            f"DELETE FROM {self.binds_table} WHERE chat_id = ?", (chat_id,)
        )
        self._conn().commit()
        return cursor.rowcount > 0

    def list_binds(self) -> List[Dict[str, Any]]:
        rows = self._conn().execute(
            f"SELECT chat_id, session_id, created_at FROM {self.binds_table} "
            "ORDER BY created_at DESC"
        ).fetchall()
        return [
            {"chat_id": r[0], "session_id": r[1], "created_at": r[2]} for r in rows
        ]

    # ------------------------------------------------------------------ #
    # 消息处理（平台无关）
    # ------------------------------------------------------------------ #

    def _is_allowed(self, chat_id: str) -> bool:
        return chat_id in set(self.allowed_chat_ids)

    def _reply_text(self, chat_id: str, text: str) -> None:
        self.send_reply(chat_id, text)

    def process_message(self, chat_id: str, text: str) -> Optional[str]:
        """白名单 → 命令分发 → LLM 对话（parse 之后的平台无关主路径）"""
        if not self._is_allowed(chat_id):
            self.stats.rejected += 1
            logger.warning("网关拒绝未授权 chat: %s", chat_id[:8])
            self._reply_text(
                chat_id,
                "此 Sage 实例未授权该对话。请在服务端配置白名单后重试。",
            )
            return "unauthorized"

        # 命令不进 LLM 对话
        if text.startswith("/"):
            reply = self._handle_command(text, chat_id)
            if reply is not None:
                self._reply_text(chat_id, reply)
                return reply

        reply = self._chat(text, chat_id)
        self._reply_text(chat_id, reply)
        self.stats.messages_replied += 1
        return reply

    def _chat(self, text: str, chat_id: str) -> str:
        """会话绑定 + 历史拼装（token 预算）+ LLM 单轮 + 消息落库"""
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
        kept, omitted = history_budget(history)
        history = kept

        client = self._resolve_llm(session_id)
        if client is None:
            reply = "（Sage 未配置可用的 LLM 端点，请在设置页配置后再试。）"
        else:
            import asyncio

            messages = [{"role": m.role, "content": m.content} for m in history]
            if omitted > 0:
                messages.insert(
                    0,
                    {
                        "role": "system",
                        "content": f"（早期 {omitted} 条对话已省略，仅保留最近内容。）",
                    },
                )
            try:
                response = asyncio.run(client.chat(messages))
                reply = (response.content or "").strip() or "（空响应，请重试。）"
            except Exception as exc:  # noqa: BLE001 — LLM 故障降级为错误提示
                logger.warning("网关 LLM 调用失败: %s", exc)
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
            logger.warning("网关 LLM 解析失败: %s", exc)
            return None

    # ------------------------------------------------------------------ #
    # 审批转发与命令（平台无关；发送经 _reply_text → send_reply）
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
        """处理 /approve /deny /pending /status /reset /help 命令。

        Returns:
            回复文本；非网关命令（None）则继续走 LLM 对话。
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
            if gate is None or not gate.answer(
                req.request_id, approved=cmd == "/approve"
            ):
                return f"审批 {parts[1]} 已失效或已处理"
            verb = "已批准" if cmd == "/approve" else "已拒绝"
            logger.info(
                "网关审批: %s %s (by chat %s)", verb, req.request_id, chat_id[:8]
            )
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

        if cmd == "/reset":
            self.unbind_chat(chat_id)
            new_session = self._session_for_chat(chat_id)
            return f"会话已重置（新会话 {new_session[:8]}…）。"

        if cmd == "/help":
            return (
                "Sage 网关命令:\n"
                "/pending — 查看待审批请求\n"
                "/approve <短id> — 批准\n"
                "/deny <短id> — 拒绝\n"
                "/status — 网关统计\n"
                "/reset — 重置本对话（全新上下文）\n"
                "/help — 命令总览\n"
                "其他文本直接与 Sage 对话。"
            )

        if cmd.startswith("/"):
            return f"未知命令 {cmd}。发送 /help 查看命令总览。"

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
            for chat_id in self.allowed_chat_ids:
                try:
                    self._reply_text(chat_id, body)
                    forwarded += 1
                except Exception as exc:  # noqa: BLE001 — 单 chat 失败不中断
                    logger.warning("审批转发失败 (chat=%s): %s", chat_id[:8], exc)
        return forwarded

    # ------------------------------------------------------------------ #
    # 轮询（平台无关；事件获取经 fetch_updates）
    # ------------------------------------------------------------------ #

    def poll_once(self) -> int:
        """长轮询一次并逐条处理。返回处理的 update 数（崩溃安全续传）。"""
        try:
            updates = self.fetch_updates()
        except Exception as exc:  # noqa: BLE001 — 网络抖动下一轮再试
            self.stats.errors += 1
            logger.warning("网关 fetch_updates 失败: %s", exc)
            return 0
        for update in updates:
            self.offset = max(self.offset, int(update.get(self.event_id_key, 0)) + 1)
            try:
                self.handle_update(update)
            except Exception as exc:  # noqa: BLE001 — 单条失败不中断轮询
                self.stats.errors += 1
                logger.warning("网关 update 处理失败: %s", exc)
        # 转发新的挂起审批到白名单 chats
        try:
            self._forward_new_approvals()
        except Exception as exc:  # noqa: BLE001 — 转发失败不中断轮询
            logger.warning("审批转发失败: %s", exc)
        return len(updates)

    def start_polling(self, poll_interval_seconds: float = 3.0) -> None:
        """启动后台长轮询守护线程（幂等）"""
        if getattr(self, "_poll_thread", None) and self._poll_thread.is_alive():
            return
        self._running = True

        def _loop() -> None:
            while self._running:
                try:
                    self.poll_once()
                except Exception as exc:  # noqa: BLE001 — 循环必须存活
                    logger.warning("网关轮询循环异常: %s", exc)
                time.sleep(poll_interval_seconds)

        self._poll_thread = threading.Thread(
            target=_loop, name="gateway-poll", daemon=True
        )
        self._poll_thread.start()
        logger.info("网关轮询线程已启动")

    def stop_polling(self) -> None:
        """停止轮询线程（线程为 daemon，进程退出亦可兜底）"""
        self._running = False
