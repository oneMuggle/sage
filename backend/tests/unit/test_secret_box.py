"""SecretBox(L15)单元测试 — API Key 落库静态加密。

覆盖:
- test scheme(base64)加解密 roundtrip / 非密文透传 / 畸形密文报错
- app_settings 包装: 扁平 endpoints + llm.endpoints 嵌套 + 空/非字符串跳过 + 幂等
- SettingsRepository 字符串层咽喉点: set_json 落库密文、get_json 回明文
- scheme=none 诚实降级: 原样落库、迁移 no-op
- migrate_plaintext_settings: 历史明文行一次性加密
- Windows 真实 DPAPI roundtrip(非 win32 skip)

CI 确定性: 除 DPAPI 用例外, 一律强制 SAGE_SECRET_SCHEME=test。
"""

from __future__ import annotations

import json

import pytest

from backend.data.settings_repo import SettingsRepository
from backend.services import secret_box
from backend.services.secret_box import (
    SecretBoxError,
    decrypt_secret,
    encrypt_secret,
    is_wrapped,
    migrate_plaintext_settings,
    unwrap_app_settings,
    wrap_app_settings,
    wrap_settings_json,
)

pytestmark = [pytest.mark.unit]

_SCHEME_TEST = {"SAGE_SECRET_SCHEME": "test"}
_SCHEME_NONE = {"SAGE_SECRET_SCHEME": "none"}


@pytest.fixture(autouse=True)
def _forced_scheme(monkeypatch):
    """默认强制 test scheme; 需要 none/真实平台时在用例内覆写。"""
    monkeypatch.setenv("SAGE_SECRET_SCHEME", "test")


# ==================== 原语 ====================


class TestPrimitives:
    def test_roundtrip(self):
        stored = encrypt_secret("sk-abc123", "ep-1")
        assert is_wrapped(stored)
        assert stored.startswith("enc:test:v1:")
        assert "sk-abc123" not in stored
        assert decrypt_secret(stored) == "sk-abc123"

    def test_decrypt_passthrough_plaintext(self):
        assert decrypt_secret("sk-raw") == "sk-raw"

    def test_decrypt_malformed_raises(self):
        with pytest.raises(SecretBoxError):
            decrypt_secret("enc:test:v0:bogus")

    def test_scheme_none_keeps_plaintext(self, monkeypatch):
        monkeypatch.setenv("SAGE_SECRET_SCHEME", "none")
        assert encrypt_secret("sk-abc") == "sk-abc"
        assert not is_wrapped("sk-abc")


# ==================== app_settings 包装 ====================


def _flat_settings(key="sk-live-1"):
    return {
        "endpoints": [
            {"id": "ep-a", "name": "A", "baseUrl": "https://a", "apiKey": key},
            {"id": "ep-b", "name": "B", "baseUrl": "https://b", "apiKey": ""},
        ],
        "chatModel": "gpt",
    }


class TestAppSettingsWrap:
    def test_wrap_flat_and_nested(self):
        data = _flat_settings()
        data["llm"] = {"endpoints": [{"id": "ep-c", "apiKey": "sk-nested"}]}
        wrapped = wrap_app_settings(data)
        assert wrapped["endpoints"][0]["apiKey"].startswith("enc:test:v1:")
        assert wrapped["endpoints"][1]["apiKey"] == ""  # 空 key 不包装
        assert wrapped["llm"]["endpoints"][0]["apiKey"].startswith("enc:test:v1:")

    def test_wrap_idempotent(self):
        once = wrap_app_settings(_flat_settings())
        twice = wrap_app_settings(once)
        assert once["endpoints"][0]["apiKey"] == twice["endpoints"][0]["apiKey"]

    def test_wrap_non_dict_passthrough(self):
        assert wrap_app_settings(None) is None
        assert wrap_app_settings([1]) == [1]

    def test_unwrap_roundtrip(self):
        wrapped = wrap_app_settings(_flat_settings("sk-live-9"))
        unwrapped = unwrap_app_settings(wrapped)
        assert unwrapped["endpoints"][0]["apiKey"] == "sk-live-9"

    def test_unwrap_corrupted_clears_key(self):
        wrapped = wrap_app_settings(_flat_settings())
        wrapped["endpoints"][0]["apiKey"] = "enc:test:v1:###not-base64###"
        unwrapped = unwrap_app_settings(wrapped)
        assert unwrapped["endpoints"][0]["apiKey"] == ""

    def test_wrap_json_string_level(self):
        raw = json.dumps(_flat_settings("sk-js"), ensure_ascii=False)
        wrapped_raw = wrap_settings_json(raw)
        assert "sk-js" not in wrapped_raw
        assert json.loads(wrapped_raw)["endpoints"][0]["apiKey"].startswith("enc:")


# ==================== SettingsRepository 咽喉点 ====================


class TestSettingsRepoIntegration:
    def test_set_json_stores_ciphertext_get_json_returns_plaintext(self):
        repo = SettingsRepository()
        repo.set_json("app_settings", _flat_settings("sk-atrest"), category="general")

        # 直接读原始行（绕过解密咽喉点）—— 落库必须是密文
        row = repo._conn().execute(
            "SELECT value FROM preferences WHERE key = ?", ("app_settings",)
        ).fetchone()
        assert "sk-atrest" not in row["value"]
        assert "enc:test:v1:" in row["value"]

        # 读路径应透明解密回明文
        data = repo.get_json("app_settings")
        assert data["endpoints"][0]["apiKey"] == "sk-atrest"

    def test_scheme_none_stores_plaintext(self, monkeypatch):
        monkeypatch.setenv("SAGE_SECRET_SCHEME", "none")
        repo = SettingsRepository()
        repo.set_json("app_settings", _flat_settings("sk-plain-ok"), category="general")
        row = repo._conn().execute(
            "SELECT value FROM preferences WHERE key = ?", ("app_settings",)
        ).fetchone()
        assert "sk-plain-ok" in row["value"]  # 诚实降级: 明文落库 + doctor 告警
        assert repo.get_json("app_settings")["endpoints"][0]["apiKey"] == "sk-plain-ok"

    def test_corrupted_json_fail_open(self):
        repo = SettingsRepository()
        repo.set("app_settings", "{not-json", category="general")
        assert repo.get("app_settings") == "{not-json"


# ==================== 启动迁移 ====================


class TestMigration:
    def test_migrates_plaintext_row(self):
        repo = SettingsRepository()
        raw = json.dumps(_flat_settings("sk-legacy"), ensure_ascii=False)
        # 造一条"历史明文行" — 必须绕过 set() 的透明加密, 直接改原始行
        repo.set("app_settings", "{}", category="general")
        repo._conn().execute(
            "UPDATE preferences SET value = ? WHERE key = ?", (raw, "app_settings")
        )
        repo._conn().commit()

        report = migrate_plaintext_settings()
        assert report["encrypted_now"] == 1

        row = repo._conn().execute(
            "SELECT value FROM preferences WHERE key = ?", ("app_settings",)
        ).fetchone()
        assert "sk-legacy" not in row["value"]
        assert repo.get_json("app_settings")["endpoints"][0]["apiKey"] == "sk-legacy"

    def test_migrate_noop_when_no_settings(self):
        repo = SettingsRepository()
        repo._conn().execute("DELETE FROM preferences WHERE key = 'app_settings'")
        repo._conn().commit()
        report = migrate_plaintext_settings()
        assert report.get("skipped") == "no_settings"

    def test_migrate_idempotent(self):
        repo = SettingsRepository()
        repo.set_json("app_settings", _flat_settings("sk-twice"), category="general")
        first = migrate_plaintext_settings()
        second = migrate_plaintext_settings()
        assert first["encrypted_now"] >= 0
        assert second["encrypted_now"] == 0


# ==================== Windows 真实 DPAPI ====================


@pytest.mark.skipif(secret_box.sys.platform != "win32", reason="DPAPI 仅 Windows")
class TestDpapiReal:
    def test_roundtrip(self, monkeypatch):
        monkeypatch.setenv("SAGE_SECRET_SCHEME", "dpapi")
        stored = encrypt_secret("sk-dpapi-real", "ep-dpapi")
        assert stored.startswith("enc:dpapi:v1:")
        assert decrypt_secret(stored) == "sk-dpapi-real"
