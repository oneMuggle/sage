"""ArenaRegistrationService 状态机测试。

全部依赖注入假体：假邮箱 provider、假 CDP 句柄、假浏览器启动/关闭，
账号池用真实 ArenaAccountService（临时 SQLite）验证真实入池行为。
"""

from __future__ import annotations

import contextlib
import os
import tempfile
import time
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet

from backend.config.arena_automation import ArenaAutomationConfig
from backend.services.arena_accounts import ArenaAccountService
from backend.services.arena_registration import (
    DEFAULT_SUBJECT_PATTERN,
    ArenaRegistrationService,
    RegistrationConflictError,
    RegistrationError,
    RegistrationNotFoundError,
    RegistrationState,
    gen_password,
    validate_password,
)
from backend.services.temporary_mail.base import Mailbox, TemporaryMailProvider

# ---------------------------------------------------------------------------
# 假体
# ---------------------------------------------------------------------------

VERIFY_LINK = "https://arena.ai/nextjs-api/callback?token=pkce_abc"


class FakeMailState:
    """跨 provider 实例共享的收发信状态（factory 每次新实例）。"""

    def __init__(self):
        self.pending: list = []
        self.created: int = 0
        self.destroyed: int = 0


class FakeProvider(TemporaryMailProvider):
    name = "fake"

    def __init__(self, state: FakeMailState):
        self._state = state

    async def create_mailbox(self) -> Mailbox:
        self._state.created += 1
        return Mailbox(
            email=f"tmp{self._state.created}@fake.example",
            password="pw",
            provider_token="tok",
            provider="fake",
        )

    async def wait_for_message(self, mailbox, subject_pattern=DEFAULT_SUBJECT_PATTERN,
                               body_pattern=None, timeout_sec=1, poll_interval_sec=1):
        if self._state.pending:
            return self._state.pending.pop(0)
        return None

    async def destroy_mailbox(self, mailbox) -> None:
        self._state.destroyed += 1

    async def wait_for_code(self, mailbox, subject_pattern=DEFAULT_SUBJECT_PATTERN,
                            timeout_sec=1, poll_interval_sec=1):
        return None

    async def _fetch_messages(self, mailbox, since_timestamp=None):
        return []

    async def aclose(self) -> None:
        pass


class FakeCdpHandle:
    """最小 CDP 句柄：记录调用，按表达式关键词返回值。"""

    def __init__(self):
        self.calls: list = []
        self.captcha = False
        self.current_url = "about:blank"

    def cdp_command(self, method, params=None, **_):
        self.calls.append((method, params))
        if method == "Page.navigate":
            self.current_url = (params or {}).get("url", self.current_url)
            return {}
        if method == "Runtime.evaluate":
            return self._eval((params or {}).get("expression", ""))
        return {}

    def _eval(self, expr: str):
        if "location.href" in expr:
            return {"result": {"value": self.current_url}}
        if "grecaptcha" not in expr and "iframe" in expr:
            return {"result": {"value": self.captcha}}
        if "input[type=password]" in expr:
            # length 表达式返回数字；focus 表达式返回 True
            if "els[" in expr:
                return {"result": {"value": True}}
            return {"result": {"value": 2}}
        if "querySelector" in expr:
            return {"result": {"value": True}}
        return {"result": {"value": None}}


class FakeBrowsers:
    def __init__(self):
        self.launched = 0
        self.closed: list = []

    def launch(self):
        self.launched += 1
        return SimpleNamespace(browser_id=f"b{self.launched}")

    def close(self, session):
        self.closed.append(session.browser_id)


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------

@pytest.fixture()
def pool():
    fd, path = tempfile.mkstemp(suffix=".sqlite")
    os.close(fd)
    service = ArenaAccountService(db_path=path, encryption_key=Fernet.generate_key())
    yield service
    service.close()  # Windows：连接未关闭时 unlink 报 WinError 32
    with contextlib.suppress(PermissionError):
        os.unlink(path)


def make_service(pool, config=None, mail_state=None):
    config = config or ArenaAutomationConfig(enabled=True)
    mail_state = mail_state or FakeMailState()
    browsers = FakeBrowsers()
    service = ArenaRegistrationService(
        config,
        account_service=pool,
        provider_factory=lambda: FakeProvider(mail_state),
        launch_browser_fn=browsers.launch,
        cdp_handle_factory=lambda session: FakeCdpHandle(),
        close_browser_fn=browsers.close,
        ttl_sec=60,
    )
    # 测试可达性：句柄是每次工厂新建的 —— 暴露最近一次供断言
    handles: list = []
    orig_factory = service._cdp_handle_factory

    def recording_factory(session):
        handle = orig_factory(session)
        handles.append(handle)
        return handle

    service._cdp_handle_factory = recording_factory
    return service, mail_state, browsers, handles


def wait_for_state(service, state: RegistrationState, timeout: float = 5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            status = service.status()
        except RegistrationError:
            status = None
        if status is not None and status["state"] == state.value:
            return status
        time.sleep(0.02)
    raise AssertionError(f"等待状态 {state.value} 超时，当前: {service.status()['state']}")


# ---------------------------------------------------------------------------
# 密码规则
# ---------------------------------------------------------------------------

def test_validate_password_rules():
    assert validate_password("Str0ng!Pass") is None
    assert validate_password("short1!A") is None  # 8 位刚好
    assert "至少 8 位" in (validate_password("Ab1!x") or "")
    assert validate_password("alllower1!") is not None
    assert validate_password("ALLUPPER1!") is not None
    assert validate_password("NoDigits!!") is not None
    assert validate_password("NoSymbol11A") is not None
    assert validate_password("") is not None


def test_gen_password_always_valid():
    for _ in range(30):
        assert validate_password(gen_password()) is None


# ---------------------------------------------------------------------------
# 状态机
# ---------------------------------------------------------------------------

def test_status_before_start_raises_not_found(pool):
    service, *_ = make_service(pool)
    with pytest.raises(RegistrationNotFoundError):
        service.status()


def test_start_opens_browser_and_reaches_awaiting_signup(pool):
    service, mail_state, browsers, handles = make_service(pool)
    status = service.start()
    assert status["state"] == RegistrationState.AWAITING_SIGNUP.value
    assert status["email_filled"] is True  # FakeCdpHandle 命中 querySelector
    assert status["email"].startswith("tmp")
    assert browsers.launched == 1
    assert mail_state.created == 1
    # 清理，避免后台线程泄漏到其他用例
    service.cancel()


def test_second_start_conflicts(pool):
    service, *_ = make_service(pool)
    service.start()
    with pytest.raises(RegistrationConflictError):
        service.start()
    service.cancel()


def test_verification_link_extraction_flow(pool):
    service, mail_state, browsers, handles = make_service(pool)
    mail_state.pending.append(
        {"id": "m1", "subject": "Verify your email", "body": f"click {VERIFY_LINK}"}
    )
    service.start()
    status = wait_for_state(service, RegistrationState.VERIFICATION_READY)
    assert status["verification_link"] == VERIFY_LINK
    service.cancel()


def test_open_verification_navigates_and_advances(pool):
    service, mail_state, browsers, handles = make_service(pool)
    mail_state.pending.append(
        {"id": "m1", "subject": "Verify", "body": f"go {VERIFY_LINK}"}
    )
    service.start()
    wait_for_state(service, RegistrationState.VERIFICATION_READY)
    status = service.open_verification()
    assert status["state"] == RegistrationState.AWAITING_PASSWORD.value
    handle = handles[-1]
    navigate_calls = [c for c in handle.calls if c[0] == "Page.navigate"]
    assert any(VERIFY_LINK in str(c[1]) for c in navigate_calls)
    service.cancel()


def test_set_password_completes_and_persists(pool):
    service, mail_state, browsers, handles = make_service(pool)
    mail_state.pending.append({"id": "m1", "subject": "Verify", "body": VERIFY_LINK})
    service.start()
    wait_for_state(service, RegistrationState.VERIFICATION_READY)
    service.open_verification()
    account = service.set_password("Str0ng!Pass")
    # 返回值 = 入池账号（密码已剥离）
    assert account["email"].startswith("tmp")
    assert "password" not in account
    assert service.status()["state"] == RegistrationState.COMPLETED.value
    # 入池校验（真实 SQLite）
    accounts = pool.list_accounts()
    assert len(accounts) == 1
    assert accounts[0]["email"] == account["email"]
    # 资源清理
    assert mail_state.destroyed >= 1
    assert len(browsers.closed) == 1
    # 终态后 status 仍可读（供 UI 展示最终结果）
    assert service.status()["state"] == RegistrationState.COMPLETED.value


def test_set_password_weak_rejected_state_unchanged(pool):
    service, mail_state, *_ = make_service(pool)
    mail_state.pending.append({"id": "m1", "subject": "Verify", "body": VERIFY_LINK})
    service.start()
    wait_for_state(service, RegistrationState.VERIFICATION_READY)
    service.open_verification()
    with pytest.raises(ValueError, match="密码不满足要求"):
        service.set_password("weak")
    assert service.status()["state"] == RegistrationState.AWAITING_PASSWORD.value
    service.cancel()


def test_set_password_manual_skips_fill(pool):
    service, mail_state, browsers, handles = make_service(pool)
    mail_state.pending.append({"id": "m1", "subject": "Verify", "body": VERIFY_LINK})
    service.start()
    wait_for_state(service, RegistrationState.VERIFICATION_READY)
    service.open_verification()
    handle = handles[-1]
    service.set_password("Str0ng!Pass", manual=True)
    eval_calls = [c for c in handle.calls if c[0] == "Runtime.evaluate"
                  and "input[type=password]" in str(c[1])]
    assert eval_calls == []  # manual：不代填
    assert len(pool.list_accounts()) == 1


def test_max_accounts_enforced(pool):
    pool.create_account(email="taken@fake.example", password="Str0ng!Pass")
    config = ArenaAutomationConfig(enabled=True, max_accounts=1)
    service, mail_state, *_ = make_service(pool, config=config)
    mail_state.pending.append({"id": "m1", "subject": "Verify", "body": VERIFY_LINK})
    service.start()
    wait_for_state(service, RegistrationState.VERIFICATION_READY)
    service.open_verification()
    with pytest.raises(RegistrationError, match="上限"):
        service.set_password("Str0ng!Pass")
    assert service.status()["state"] == RegistrationState.FAILED.value
    assert len(pool.list_accounts()) == 1  # 原账号未受影响


def test_cancel_cleans_up(pool):
    service, mail_state, browsers, _ = make_service(pool)
    service.start()
    result = service.cancel()
    assert result["state"] == RegistrationState.CANCELLED.value
    assert mail_state.destroyed == 1
    assert len(browsers.closed) == 1
    # 终态后 status 仍可读，展示 cancelled
    assert service.status()["state"] == RegistrationState.CANCELLED.value


def test_ttl_expiry_marks_expired(pool):
    config = ArenaAutomationConfig(enabled=True)
    service, mail_state, browsers, _ = make_service(pool, config=config)
    service._ttl_sec = 0  # 立即过期
    service.start()
    status = wait_for_state(service, RegistrationState.EXPIRED)
    assert "超时" in status["error"]
    assert len(browsers.closed) == 1
    assert mail_state.destroyed >= 1


def test_browser_launch_failure_marks_failed(pool):
    config = ArenaAutomationConfig(enabled=True)
    mail_state = FakeMailState()
    browsers = FakeBrowsers()

    def broken_launch():
        raise RuntimeError("no browser installed")

    service = ArenaRegistrationService(
        config,
        account_service=pool,
        provider_factory=lambda: FakeProvider(mail_state),
        launch_browser_fn=broken_launch,
        close_browser_fn=browsers.close,
    )
    with pytest.raises(RegistrationError, match="浏览器启动失败"):
        service.start()
    assert service.status()["state"] == RegistrationState.FAILED.value
    assert mail_state.destroyed == 1  # 邮箱已回收
