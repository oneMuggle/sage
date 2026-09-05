"""network check 测试 —— 验证 network_policy 配置合法性与 httpx 依赖。

场景覆盖:
- 未配置（默认 ONLINE）→ INFO
- ONLINE + httpx 可用 → INFO
- OFFLINE → INFO（气隙模式）
- INTRANET + 合法 allowed_hosts → INFO
- INTRANET + allowed_hosts 为空 → WARN
- INTRANET + allowed_hosts 格式非法 → WARN
- mode 非法 → WARN（fail-safe 到 ONLINE）
- JSON 非法 → WARN（fail-safe 到 ONLINE）
- 非 dict JSON → WARN
- httpx 不可用 → CRITICAL
"""
from __future__ import annotations

import json
from typing import Optional

from backend.cli.doctor import Severity


class _FakeRepo:
    def __init__(self, raw: Optional[str]) -> None:
        self._raw = raw

    def get(self, key: str) -> Optional[str]:
        assert key == "network_policy"
        return self._raw


def _make_check():
    from backend.cli.checks.network import NetworkCheck

    return NetworkCheck()


def _run_with_repo(raw: Optional[str]):
    return _make_check().run_with_repo(_FakeRepo(raw))


class TestNetworkCheck:
    def test_no_config_defaults_to_online_info(self) -> None:
        result = _run_with_repo(None)
        assert result.severity == Severity.INFO
        assert "online" in result.message.lower()

    def test_online_mode_info(self) -> None:
        raw = json.dumps({"mode": "online", "allowed_hosts": [], "insecure_tls_hosts": []})
        result = _run_with_repo(raw)
        assert result.severity == Severity.INFO
        assert "online" in result.message.lower()

    def test_offline_mode_info(self) -> None:
        raw = json.dumps({"mode": "offline", "allowed_hosts": [], "insecure_tls_hosts": []})
        result = _run_with_repo(raw)
        assert result.severity == Severity.INFO
        assert "offline" in result.message.lower()

    def test_intranet_with_valid_hosts_info(self) -> None:
        raw = json.dumps(
            {
                "mode": "intranet",
                "allowed_hosts": ["*.cnki.net", "wiki.internal"],
                "insecure_tls_hosts": [],
            }
        )
        result = _run_with_repo(raw)
        assert result.severity == Severity.INFO
        assert "intranet" in result.message.lower()

    def test_intranet_empty_hosts_warn(self) -> None:
        raw = json.dumps({"mode": "intranet", "allowed_hosts": [], "insecure_tls_hosts": []})
        result = _run_with_repo(raw)
        assert result.severity == Severity.WARN
        assert "allowed_hosts" in result.message or "白名单" in result.message

    def test_intranet_invalid_host_pattern_warn(self) -> None:
        # "*" 太宽 → NetworkPolicy.from_config 抛 ValueError
        raw = json.dumps({"mode": "intranet", "allowed_hosts": ["*"], "insecure_tls_hosts": []})
        result = _run_with_repo(raw)
        assert result.severity == Severity.WARN
        assert "非法" in result.message or "illegal" in result.message.lower()

    def test_invalid_mode_warn(self) -> None:
        raw = json.dumps({"mode": "airplane", "allowed_hosts": [], "insecure_tls_hosts": []})
        result = _run_with_repo(raw)
        assert result.severity == Severity.WARN

    def test_malformed_json_warn(self) -> None:
        result = _run_with_repo("{not valid json")
        assert result.severity == Severity.WARN

    def test_non_dict_json_warn(self) -> None:
        result = _run_with_repo('"just a string"')
        assert result.severity == Severity.WARN


class TestNetworkCheckHttpx:
    def test_httpx_missing_critical(self) -> None:
        """ONLINE 模式下 httpx 缺失 → CRITICAL。"""
        import sys

        # patch __import__ 让 httpx 加载失败
        real_import = __import__

        def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "httpx":
                raise ImportError("Simulated missing httpx")
            return real_import(name, globals, locals, fromlist, level)

        # 备份并清 httpx 缓存
        had_httpx = "httpx" in sys.modules
        saved_httpx = sys.modules.get("httpx")
        sys.modules.pop("httpx", None)

        try:
            import builtins

            builtins.__import__ = fake_import
            try:
                result = _make_check().run()
            finally:
                builtins.__import__ = real_import

            assert result.severity == Severity.CRITICAL
            assert "httpx" in result.message.lower()
        finally:
            if had_httpx and saved_httpx is not None:
                sys.modules["httpx"] = saved_httpx
