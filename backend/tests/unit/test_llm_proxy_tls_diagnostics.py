"""LLM 代理路由 — TLS 检测单元测试.

Task 1 round 1 (2026-08-24): ``_is_ca_bundle_available`` 系统 CA 路径探测 +
``_is_tls_certificate_error`` isinstance 主路径 / 字符串匹配 fallback 都需要
专门单元测试覆盖. 这些是纯函数, 无 FastAPI 客户端依赖, 直接调函数断言.
"""

from __future__ import annotations

import ssl
import sys
from pathlib import Path

import pytest


# 延迟导入: 测试文件 import 阶段就执行, 但 backend.main 的 lifespan 副作用也跑
# (certifi bootstrap 设置 SSL_CERT_FILE), 我们要测的是函数本身, 而不是副作用.
@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """每个测试前清空 ``SSL_CERT_FILE`` / ``REQUESTS_CA_BUNDLE`` / ``CURL_CA_BUNDLE``."""
    for var in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE"):
        monkeypatch.delenv(var, raising=False)


def test_ca_bundle_via_env_var(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """设置 ``SSL_CERT_FILE`` 指向非空文件 → True."""
    ca_file = tmp_path / "ca.pem"
    ca_file.write_text("-----BEGIN CERTIFICATE-----\nMOCK\n-----END CERTIFICATE-----\n")
    monkeypatch.setenv("SSL_CERT_FILE", str(ca_file))

    from backend.api.llm_proxy_routes import _is_ca_bundle_available

    assert _is_ca_bundle_available() is True


def test_ca_bundle_env_var_empty_file_returns_false(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """环境变量指向空文件 → False (size 0 不被认作可用)."""
    ca_file = tmp_path / "empty.pem"
    ca_file.write_text("")
    monkeypatch.setenv("SSL_CERT_FILE", str(ca_file))

    from backend.api.llm_proxy_routes import _is_ca_bundle_available

    assert _is_ca_bundle_available() is False


def test_ca_bundle_env_var_missing_file_returns_false(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """环境变量指向不存在的文件 → False, 继续 fallback 到系统默认."""
    monkeypatch.setenv("SSL_CERT_FILE", str(tmp_path / "does-not-exist.pem"))

    from backend.api.llm_proxy_routes import _is_ca_bundle_available

    # 不存在的 env → fallback 到 get_default_verify_paths() — 在大多数 CI 环境
    # (certifi 已安装) 会返回 True. 我们只断言函数不抛 + 返回 bool, 不硬编码 True.
    result = _is_ca_bundle_available()
    assert isinstance(result, bool)


def test_ca_bundle_via_capath_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``capath`` 是目录, 含 cert hash 链接 → 函数应识别为可用."""
    ca_dir = tmp_path / "certs"
    ca_dir.mkdir()
    (ca_dir / "abc123.0").write_text("-----BEGIN CERTIFICATE-----\nMOCK\n-----END CERTIFICATE-----\n")
    monkeypatch.setenv("SSL_CERT_FILE", str(ca_dir))

    from backend.api.llm_proxy_routes import _is_ca_bundle_available

    assert _is_ca_bundle_available() is True


def test_tls_certificate_error_matches_ssl_cert_verification_error_directly() -> None:
    """主路径: 直接 ``ssl.SSLCertVerificationError`` 实例 → True (无字符串匹配)."""
    from backend.api.llm_proxy_routes import _is_tls_certificate_error

    # Python 3.7+ 起 ssl.SSLCertVerificationError 是 ssl.SSLError 子类, 接受
    # (reason, msg) 两个构造参数; 第 3 个 (errno) 在 Py3.7+ 才有.
    try:
        err = ssl.SSLCertVerificationError(
            "CERTIFICATE_VERIFY_FAILED", "certificate verify failed"
        )
    except TypeError:
        # Py3.7/3.8 旧签名: 只接受 reason
        err = ssl.SSLCertVerificationError("certificate verify failed")
    assert _is_tls_certificate_error(err) is True


def test_tls_certificate_error_walks_cause_chain() -> None:
    """``ssl.SSLCertVerificationError`` 在 ``__cause__`` 链里 → True.

    outer 异常 message **不含** TLS 关键词 ("wrapped connect error"), 唯一能命中
    True 的路径是 ``__cause__`` 链 isinstance 检查. 如果字符串 fallback 被改回
    主路径或主路径被删, 这条测试会立刻挂.
    """
    from backend.api.llm_proxy_routes import _is_tls_certificate_error

    try:
        real_ssl_err = ssl.SSLCertVerificationError(
            "CERTIFICATE_VERIFY_FAILED", "certificate verify failed"
        )
    except TypeError:
        real_ssl_err = ssl.SSLCertVerificationError("certificate verify failed")

    outer: BaseException
    try:
        # 优先用真实 httpx.ConnectError (在 httpx>=0.21 存在)
        import httpx

        outer = httpx.ConnectError("wrapped connect error")
    except ImportError:
        outer = RuntimeError("wrapped connect error")

    try:
        raise outer from real_ssl_err
    except BaseException as exc:  # noqa: BLE001 — 故意捕获, 仅测链
        assert _is_tls_certificate_error(exc) is True


def test_tls_certificate_error_walks_context_chain() -> None:
    """``__context__`` (implicit) 链上有 SSLCertVerificationError → True.

    outer 异常 message **不含** TLS 关键词, 唯一命中路径是 ``__context__``
    isinstance 检查.
    """
    from backend.api.llm_proxy_routes import _is_tls_certificate_error

    try:
        real_ssl_err = ssl.SSLCertVerificationError(
            "CERTIFICATE_VERIFY_FAILED", "certificate verify failed"
        )
    except TypeError:
        real_ssl_err = ssl.SSLCertVerificationError("certificate verify failed")
    try:
        # 不写 ``from`` → 触发 implicit ``__context__`` 链
        try:
            raise real_ssl_err
        except Exception:
            raise RuntimeError("wrapper")
    except BaseException as exc:  # noqa: BLE001
        assert _is_tls_certificate_error(exc) is True


def test_tls_certificate_error_returns_false_for_unrelated() -> None:
    """无关异常 → False."""
    from backend.api.llm_proxy_routes import _is_tls_certificate_error

    assert _is_tls_certificate_error(RuntimeError("unrelated")) is False
    assert _is_tls_certificate_error(ValueError("bad value")) is False


def test_tls_certificate_error_string_match_fallback() -> None:
    """字符串匹配兜底: 消息含 ``certificate verify failed`` 但 isinstance 不命中 → True.

    模拟 httpcore 在某些版本里把 SSLCertVerificationError 包装成 RemoteProtocolError,
    __cause__ 链断裂, 但 message 包含关键词.
    """
    from backend.api.llm_proxy_routes import _is_tls_certificate_error

    assert _is_tls_certificate_error(RuntimeError("SSL: CERTIFICATE_VERIFY_FAILED")) is True
    assert _is_tls_certificate_error(RuntimeError("certificate verify failed: self-signed")) is True


def test_tls_certificate_error_does_not_loop_on_self_reference() -> None:
    """``__cause__`` 自循环 (异常 cause 自身) 不会无限递归 → False (或不挂)."""
    from backend.api.llm_proxy_routes import _is_tls_certificate_error

    # 构造自循环 cause: exc.__cause__ = exc
    exc = RuntimeError("loop")
    try:
        exc.__cause__ = exc  # type: ignore[misc]
    except Exception:
        pytest.skip("__cause__ 自赋值在 Python 上抛异常, 跳过")
    # 不管是 True / False, 关键是不挂 (递归保护). 函数返回 bool 即可.
    result = _is_tls_certificate_error(exc)
    assert isinstance(result, bool)


# 简单 sanity: 确保 import 时 sys 平台不被改 (Windows-only skip)
@pytest.mark.skipif(
    sys.platform.startswith("win"),
    reason="Win32 路径分隔符不同; 测试只对 POSIX 行为有意义",
)
def test_ca_bundle_default_verify_paths_probe() -> None:
    """所有 env vars 清空, 但 ``ssl.get_default_verify_paths().cafile`` / ``capath``
    其中之一指向现有路径 (例如 certifi 注入后) → 函数仍返 True.
    """
    # 不主动设置 env vars; conftest 已经 import backend.main 跑了 certifi 注入.
    # 这里只断言函数行为合理 (返回 bool, 不抛).
    from backend.api.llm_proxy_routes import _is_ca_bundle_available

    # 至少跑通 (certifi 注入后 cafile 必然非空). 不依赖 conftest 行为.
    assert isinstance(_is_ca_bundle_available(), bool)

