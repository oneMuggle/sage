"""单账号注册辅助服务（人工验证码 · 单实例 · 无批量循环）。

流程与边界
==========
用户在 UI 手动触发一次注册：

    start()                创建临时邮箱 + 打开可见浏览器进注册页 + 尽力填邮箱
        ↓（用户自己完成人机验证、自己点提交）
    awaiting_signup ──► 后台线程轮询临时邮箱
        ↓ 收到验证邮件
    verification_ready      验证链接呈给用户，由用户决定何时打开
        ↓ open_verification()（用户触发导航，或用户自己点链接后确认）
    awaiting_password
        ↓ set_password()（校验强度 → 尽力填表 → 入账号池）
    completed / failed / cancelled / expired

硬性边界（见 docs/superpowers/plans/2026-09-19-arena-register-assist-panel.md §0）：
    * 同一时刻至多一个活跃注册（含已启动的浏览器与临时邮箱）；
    * 检测到 CAPTCHA 时只提示人工处理，绝不自动出票/绕过；
    * 邮箱链接只呈给用户、按用户指令导航；
    * TTL 到期自动清理浏览器与邮箱。

浏览器 / 邮箱 provider / CDP 句柄全部依赖注入，测试用假体。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import secrets
import string
import threading
import time
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, Optional

from backend.config.arena_automation import ArenaAutomationConfig
from backend.services.arena_adapter import ArenaAdapter
from backend.services.temporary_mail import (
    DEFAULT_SUBJECT_PATTERN,
    Mailbox,
    TemporaryMailProvider,
    create_provider,
)

logger = logging.getLogger(__name__)

SIGNUP_URL = "https://arena.ai/sign-up"

#: 验证邮件正文里的 arena 链接（callback/verify 两类；站点改版可能漂移）
VERIFY_LINK_RE = re.compile(r"https://arena\.ai/[^\s\"'<>]*(?:callback|verify)[^\s\"'<>]*")

#: arena 密码规则：≥8 位，须含大写 + 小写 + 数字 + 特殊符号
_PASSWORD_RULES = (
    (lambda p: len(p) >= 8, "至少 8 位"),
    (lambda p: any(c.isupper() for c in p), "须含大写字母"),
    (lambda p: any(c.islower() for c in p), "须含小写字母"),
    (lambda p: any(c.isdigit() for c in p), "须含数字"),
    (lambda p: any(not c.isalnum() for c in p), "须含特殊符号"),
)

#: 收信轮询单次阻塞时长（内部 wait_for_message 的 timeout），到点回头检查 TTL/停止标志
_POLL_CHUNK_SEC = 10.0

DEFAULT_TTL_SEC = 1800


class RegistrationError(RuntimeError):
    """注册流程失败（转 failed 或请求非法）。"""


class RegistrationConflictError(RegistrationError):
    """已有进行中的注册 / 状态机顺序不合法（HTTP 409）。"""


class RegistrationNotFoundError(RegistrationError):
    """当前没有注册记录（HTTP 404）。"""


class RegistrationState(Enum):
    AWAITING_SIGNUP = "awaiting_signup"
    AWAITING_VERIFICATION = "awaiting_verification"
    VERIFICATION_READY = "verification_ready"
    AWAITING_PASSWORD = "awaiting_password"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


TERMINAL_STATES = {
    RegistrationState.COMPLETED,
    RegistrationState.FAILED,
    RegistrationState.CANCELLED,
    RegistrationState.EXPIRED,
}

#: 各状态给 UI 的人工操作提示
MANUAL_HINTS = {
    RegistrationState.AWAITING_SIGNUP: "请在打开的浏览器中完成人机验证并提交注册表单",
    RegistrationState.AWAITING_VERIFICATION: "注册已提交，等待验证邮件…",
    RegistrationState.VERIFICATION_READY: "验证邮件已到：点击「打开验证链接」或在浏览器中自行打开",
    RegistrationState.AWAITING_PASSWORD: "请在浏览器中设置密码（或输入相同密码由本页代填）",
}


def validate_password(password: str) -> Optional[str]:
    """返回第一条不满足的规则说明；合法返回 None。"""
    if not isinstance(password, str) or not password:
        return "密码不能为空"
    for rule, message in _PASSWORD_RULES:
        if not rule(password):
            return message
    return None


def gen_password(length: int = 14) -> str:
    """生成符合 arena 规则的密码（保证四类字符齐全）。"""
    rng = secrets.SystemRandom()
    pool = string.ascii_letters + string.digits + "!@#$%^&*"
    while True:
        pwd = [
            rng.choice(string.ascii_uppercase),
            rng.choice(string.ascii_lowercase),
            rng.choice(string.digits),
            rng.choice("!@#$%^&*"),
        ]
        pwd += [rng.choice(pool) for _ in range(max(4, length - 4))]
        rng.shuffle(pwd)
        password = "".join(pwd)
        if validate_password(password) is None:
            return password


class _BrowserCdpHandle:
    """ArenaAdapter 期望的 browser_session 协议：cdp_command(method, params)。

    把 browser_cdp 的模块级函数（需要显式 session/target）适配成对象方法。
    """

    def __init__(self, session: Any):
        self._session = session

    def cdp_command(self, method: str, params: Optional[Dict] = None, **_: Any) -> Any:
        from backend.tools.browser_cdp import cdp_command as _cdp_command

        return _cdp_command(self._session, method, params)


def _default_launch_browser() -> Any:
    from backend.tools.browser_cdp import launch_browser

    # 有头模式：用户需要亲眼看到并手动完成人机验证
    return launch_browser(headless=False)


def _default_close_browser(session: Any) -> None:
    from backend.tools.browser_cdp import _terminate_session, get_browser_manager

    get_browser_manager().remove(session.browser_id)
    _terminate_session(session)


class ArenaRegistrationService:
    """单实例注册辅助状态机。线程安全。"""

    def __init__(
        self,
        config: ArenaAutomationConfig,
        account_service: Any,
        provider_factory: Optional[Callable[[], TemporaryMailProvider]] = None,
        launch_browser_fn: Optional[Callable[[], Any]] = None,
        cdp_handle_factory: Optional[Callable[[Any], Any]] = None,
        close_browser_fn: Optional[Callable[[Any], None]] = None,
        ttl_sec: int = DEFAULT_TTL_SEC,
    ):
        self._config = config
        self._account_service = account_service
        self._provider_factory = provider_factory or (
            lambda: create_provider(config.mail_provider, config.mail_api_key)
        )
        self._launch_browser_fn = launch_browser_fn or _default_launch_browser
        self._cdp_handle_factory = cdp_handle_factory or _BrowserCdpHandle
        self._close_browser_fn = close_browser_fn or _default_close_browser
        self._ttl_sec = ttl_sec
        self._lock = threading.RLock()
        #: 当前注册记录（至多一个非终态）；dict，字段见 _new_registration
        self._reg: Optional[Dict[str, Any]] = None

    # -- public API --------------------------------------------------------

    def start(self) -> Dict[str, Any]:
        """创建临时邮箱并打开注册页。已有进行中注册时抛 Conflict（409）。

        邮箱创建与浏览器启动是真实的慢操作（秒级~30s），放在 FastAPI
        线程池线程里同步执行；占位在锁内完成，启动在锁外做，不会出现
        两个并发 start 各自启动浏览器。
        """
        with self._lock:
            self._expire_if_due()
            if self._reg is not None and self._reg["state"] not in TERMINAL_STATES:
                raise RegistrationConflictError("已有进行中的注册，请先完成或取消")
            provider = self._provider_factory()
            mailbox = asyncio.run(provider.create_mailbox())
            self._reg = self._new_registration(mailbox)
        reg = self._reg
        try:
            session = self._launch_browser_fn()
        except Exception as exc:  # noqa: BLE001 — 浏览器启动失败 → failed
            self._cleanup_mailbox(reg)
            with self._lock:
                reg["state"] = RegistrationState.FAILED
                reg["error"] = f"浏览器启动失败: {exc}"
            raise RegistrationError(reg["error"]) from exc
        with self._lock:
            reg["session"] = session
            reg["adapter"] = ArenaAdapter(self._cdp_handle_factory(session))
        # 打开注册页 + 尽力填邮箱：best-effort，失败降级为手动操作
        adapter: ArenaAdapter = reg["adapter"]
        try:
            adapter.open_page(SIGNUP_URL)
        except Exception as exc:  # noqa: BLE001
            logger.warning("打开注册页失败（降级为手动导航）: %s", exc)
        time.sleep(1.0)  # 给 SPA 一点渲染时间
        try:
            adapter.fill_signup_email(mailbox.email)
            reg["email_filled"] = True
        except Exception as exc:  # noqa: BLE001
            reg["email_filled"] = False
            logger.info("自动填邮箱未命中选择器（用户手动填写）: %s", exc)
        with self._lock:
            reg["state"] = RegistrationState.AWAITING_SIGNUP
        threading.Thread(
            target=self._mailbox_poller, args=(reg,), name="arena-mail-poll", daemon=True
        ).start()
        return self.status()

    def status(self) -> Dict[str, Any]:
        with self._lock:
            self._expire_if_due()
            if self._reg is None:
                raise RegistrationNotFoundError("没有进行中的注册")
            reg = self._reg
            captcha_present = False
            if reg["state"] == RegistrationState.AWAITING_SIGNUP:
                captcha_present = self._detect_captcha(reg)
            return {
                "registration_id": reg["id"],
                "email": reg["mailbox"].email,
                "state": reg["state"].value,
                "captcha_present": captcha_present,
                "verification_link": reg["verification_link"] or "",
                "email_filled": reg["email_filled"],
                "error": reg["error"] or "",
                "created_at": reg["created_at_wall"],
                "expires_in_sec": max(
                    0, int(reg["expires_at"] - time.monotonic())
                ),
                "manual_hint": MANUAL_HINTS.get(reg["state"], ""),
            }

    def open_verification(self) -> Dict[str, Any]:
        """在受管浏览器里打开验证链接（用户显式触发）。"""
        with self._lock:
            self._expire_if_due()
            reg = self._require_state(RegistrationState.VERIFICATION_READY)
            adapter: ArenaAdapter = reg["adapter"]
            link = reg["verification_link"]
        try:
            # 用户可能已自己点过链接：已在 set-password 页则不重复导航
            current = adapter.current_url()
            if "set-password" not in current:
                adapter.open_page(link)
        except Exception as exc:  # noqa: BLE001 — 导航失败状态不前进
            raise RegistrationError(f"打开验证链接失败: {exc}") from exc
        with self._lock:
            reg["state"] = RegistrationState.AWAITING_PASSWORD
        return self.status()

    def set_password(self, password: str, manual: bool = False) -> Dict[str, Any]:
        """校验密码强度，尽力填入设置密码表单，并把账号入池。

        manual=True：跳过代填（用户已在浏览器里手动输入相同密码）。
        """
        problem = validate_password(password)
        if problem:
            # ValueError → 路由层映射 400（状态冲突才用 409）
            raise ValueError(f"密码不满足要求：{problem}")
        with self._lock:
            self._expire_if_due()
            reg = self._require_state(RegistrationState.AWAITING_PASSWORD)
            adapter: ArenaAdapter = reg["adapter"]
        if not manual:
            try:
                adapter.fill_password_inputs(password)
            except Exception as exc:  # noqa: BLE001
                raise RegistrationError(
                    f"页面密码输入框定位失败（{exc}）；"
                    "请在浏览器中手动输入相同密码后，勾选「我已手动填写」重试"
                ) from exc
            try:
                adapter.submit_visible_form()
            except Exception as exc:  # noqa: BLE001 — 提交按钮失配：用户手动点
                logger.info("自动点提交未命中（用户手动提交）: %s", exc)
        try:
            if (
                len(self._account_service.list_accounts())
                >= self._config.max_accounts
            ):
                raise RegistrationError(
                    f"账号池已达上限 {self._config.max_accounts}，"
                    "请先删除账号或调高 arena_automation.max_accounts"
                )
            account = self._account_service.create_account(
                email=reg["mailbox"].email, password=password, notes="arena-assist"
            )
        except (RegistrationError, ValueError) as exc:
            with self._lock:
                reg["state"] = RegistrationState.FAILED
                reg["error"] = str(exc)
            self._cleanup(reg)
            raise RegistrationError(str(exc)) from exc
        with self._lock:
            reg["state"] = RegistrationState.COMPLETED
        self._cleanup(reg)
        return {k: v for k, v in account.items() if k != "password"}

    def cancel(self) -> Dict[str, Any]:
        with self._lock:
            self._expire_if_due()
            reg = self._reg
            if reg is None or reg["state"] in TERMINAL_STATES:
                raise RegistrationNotFoundError("没有可取消的注册")
            reg["state"] = RegistrationState.CANCELLED
        self._cleanup(reg)
        return {"registration_id": reg["id"], "state": reg["state"].value}

    # -- internals ----------------------------------------------------------

    def _new_registration(self, mailbox: Mailbox) -> Dict[str, Any]:
        return {
            "id": uuid.uuid4().hex[:12],
            "mailbox": mailbox,
            "state": RegistrationState.AWAITING_VERIFICATION,
            "verification_link": "",
            "email_filled": False,
            "error": "",
            "session": None,
            "adapter": None,
            "stop_event": threading.Event(),
            "created_at_wall": datetime.now(timezone.utc)  # noqa: UP017 — py38 兼容
            .replace(tzinfo=None)
            .isoformat(timespec="seconds"),
            "expires_at": time.monotonic() + self._ttl_sec,
        }

    def _require_state(self, expected: RegistrationState) -> Dict[str, Any]:
        reg = self._reg
        if reg is None or reg["state"] in TERMINAL_STATES:
            raise RegistrationConflictError("没有进行中的注册")
        if reg["state"] != expected:
            raise RegistrationConflictError(
                f"当前状态为 {reg['state'].value}，需要 {expected.value}"
            )
        return reg

    def _expire_if_due(self) -> None:
        """调用方必须已持锁。惰性过期：读状态时才清理。"""
        reg = self._reg
        if reg is None or reg["state"] in TERMINAL_STATES:
            return
        if time.monotonic() >= reg["expires_at"]:
            reg["state"] = RegistrationState.EXPIRED
            reg["error"] = "注册超时（30 分钟）"
            self._cleanup(reg)

    def _detect_captcha(self, reg: Dict[str, Any]) -> bool:
        adapter: Optional[ArenaAdapter] = reg.get("adapter")
        if adapter is None:
            return False
        try:
            return bool(adapter.detect_captcha())
        except Exception:  # noqa: BLE001 — 检测失败当无验证码，不阻塞流程
            return False

    def _mailbox_poller(self, reg: Dict[str, Any]) -> None:
        """后台收信线程：状态到 verification_ready 或终态即退出。"""
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(self._poll_loop(reg))
        except Exception as exc:  # noqa: BLE001 — 轮询崩溃不影响主流程，可手动继续
            logger.warning("收信线程异常退出: %s", exc)
        finally:
            loop.close()

    async def _poll_loop(self, reg: Dict[str, Any]) -> None:
        provider = self._provider_factory()
        try:
            while not reg["stop_event"].is_set():
                with self._lock:
                    state = reg["state"]
                    expired = time.monotonic() >= reg["expires_at"]
                if expired or state in TERMINAL_STATES:
                    return
                try:
                    message = await provider.wait_for_message(
                        reg["mailbox"],
                        subject_pattern=DEFAULT_SUBJECT_PATTERN,
                        timeout_sec=_POLL_CHUNK_SEC,
                        poll_interval_sec=3,
                    )
                except Exception as exc:  # noqa: BLE001 — provider 抖动：下轮再试
                    logger.debug("收信轮询异常（继续）: %s", exc)
                    message = None
                if message is None:
                    # 真 provider 的 wait_for_message 会阻塞一个 chunk；
                    # 假体/异常路径立即返回 —— 兜底小睡防热轮询
                    await asyncio.sleep(0.2)
                    continue
                link = self._extract_link(str(message.get("body") or ""))
                if not link:
                    logger.info("验证邮件正文未提取到链接，继续等待下一封")
                    continue
                with self._lock:
                    if reg["state"] is RegistrationState.AWAITING_SIGNUP:
                        reg["state"] = RegistrationState.VERIFICATION_READY
                    reg["verification_link"] = link
                return
        finally:
            close = getattr(provider, "aclose", None)
            if close is not None:
                with contextlib.suppress(Exception):
                    await close()

    @staticmethod
    def _extract_link(body: str) -> str:
        match = VERIFY_LINK_RE.search(body or "")
        if not match:
            return ""
        return match.group(0).replace("\\u0026", "&")

    def _cleanup_mailbox(self, reg: Dict[str, Any]) -> None:
        reg["stop_event"].set()
        try:
            provider = self._provider_factory()
            asyncio.run(provider.destroy_mailbox(reg["mailbox"]))
        except Exception as exc:  # noqa: BLE001 — best-effort
            logger.debug("销毁临时邮箱失败（忽略）: %s", exc)

    def _cleanup(self, reg: Dict[str, Any]) -> None:
        """终态清理：停轮询、销毁邮箱、关闭浏览器。幂等。"""
        self._cleanup_mailbox(reg)
        session = reg.get("session")
        if session is not None:
            try:
                self._close_browser_fn(session)
            except Exception as exc:  # noqa: BLE001
                logger.debug("关闭注册浏览器失败（忽略）: %s", exc)
            reg["session"] = None
            reg["adapter"] = None
