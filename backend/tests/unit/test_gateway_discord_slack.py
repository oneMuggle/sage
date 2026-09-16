# ruff: noqa: UP006, UP007, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""Discord / Slack 网关适配器测试（Round 16）。

覆盖：双源配置（env 优先 / settings 兜底 / kill-switch）、fetch_updates
游标推进与自环防护、白名单拒答全链路、transport 截断、status/config 路由。
"""

from __future__ import annotations

import tempfile
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.gateway_routes import router as gateway_router
from backend.gateway.discord import DiscordConfig, DiscordGateway, DiscordTransport
from backend.gateway.slack import SlackConfig, SlackGateway, SlackTransport

pytestmark = pytest.mark.unit


@pytest.fixture()
def tmp_db(monkeypatch):
    from backend.data.database import Database

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db = Database(f.name)
        db.init_db()
    import backend.data.database as db_mod

    monkeypatch.setattr(db_mod, "_db", db)
    yield db
    db.close()


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(gateway_router)
    return TestClient(app, headers={"Authorization": "Bearer test-local-auth-token"})


def _seed_settings(monkeypatch, platform, node):
    """把 app_settings.<platform> 固定为给定节点（绕过真库）。"""
    import backend.data.settings_repo as sr_mod

    state = {"app_settings": {platform: node} if node is not None else {}}
    saved = {}

    def get_json(self, key):
        return state.get(key, {})

    def set_json(self, key, value, category="general"):
        saved[key] = value
        state[key] = value

    monkeypatch.setattr(sr_mod.SettingsRepository, "get_json", get_json)
    monkeypatch.setattr(sr_mod.SettingsRepository, "set_json", set_json)
    return saved


# --------------------------------------------------------------------------- #
# stub transports
# --------------------------------------------------------------------------- #


class FakeDiscordTransport:
    """按频道返回固定消息页（旧→新）；记录 send 调用。"""

    def __init__(self, pages=None):
        # channel_id -> list[message dict]（每次 fetch 返回整页，模拟旧→新）
        self.pages = pages or {}
        self.sent = []
        self.fetch_calls = []

    def fetch_messages(self, channel_id, after_id, limit):
        self.fetch_calls.append((channel_id, after_id, limit))
        return list(self.pages.get(channel_id, []))

    def send_message(self, channel_id, text):
        self.sent.append((channel_id, text))


class FakeSlackTransport:
    """按频道返回固定 history（新→旧，conversations.history 序）。"""

    def __init__(self, pages=None):
        self.pages = pages or {}
        self.sent = []
        self.fetch_calls = []

    def fetch_history(self, channel_id, oldest_ts, limit):
        self.fetch_calls.append((channel_id, oldest_ts, limit))
        return list(self.pages.get(channel_id, []))

    def post_message(self, channel_id, text):
        self.sent.append((channel_id, text))


def _discord_gateway(tmp_db, allowed=("111111",), llm_reply="回复"):
    transport = FakeDiscordTransport()
    config = DiscordConfig(bot_token="tok", allowed_channel_ids=list(allowed))
    gateway = DiscordGateway(
        config=config, transport=transport, llm_factory=lambda _sid: _StubLLM(llm_reply), db=tmp_db
    )
    return gateway, transport


def _slack_gateway(tmp_db, allowed=("C111",), llm_reply="回复"):
    transport = FakeSlackTransport()
    config = SlackConfig(bot_token="tok", allowed_channel_ids=list(allowed))
    gateway = SlackGateway(
        config=config, transport=transport, llm_factory=lambda _sid: _StubLLM(llm_reply), db=tmp_db
    )
    return gateway, transport


class _StubLLM:
    def __init__(self, reply):
        self._reply = reply
        self.calls = []

    async def chat(self, messages):
        self.calls.append(messages)
        return SimpleNamespace(content=self._reply)


# --------------------------------------------------------------------------- #
# config 双源
# --------------------------------------------------------------------------- #


class TestDiscordConfig:
    def test_none_without_any_config(self, monkeypatch, tmp_db):
        monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
        _seed_settings(monkeypatch, "discord", None)
        assert DiscordConfig.load() is None

    def test_settings_source(self, monkeypatch, tmp_db):
        monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
        _seed_settings(
            monkeypatch,
            "discord",
            {"bot_token": "set-tok", "allowed_channel_ids": ["1", "2"]},
        )
        cfg = DiscordConfig.load()
        assert cfg is not None
        assert cfg.bot_token == "set-tok"
        assert cfg.allowed_channel_ids == ["1", "2"]

    def test_env_overrides_settings(self, monkeypatch, tmp_db):
        monkeypatch.setenv("DISCORD_BOT_TOKEN", "env-tok")
        monkeypatch.setenv("DISCORD_ALLOWED_CHANNEL_IDS", "9")
        _seed_settings(monkeypatch, "discord", {"bot_token": "set-tok"})
        cfg = DiscordConfig.load()
        assert cfg is not None
        assert cfg.bot_token == "env-tok"
        assert cfg.allowed_channel_ids == ["9"]

    def test_settings_disabled_wins_over_env(self, monkeypatch, tmp_db):
        monkeypatch.setenv("DISCORD_BOT_TOKEN", "env-tok")
        _seed_settings(monkeypatch, "discord", {"bot_token": "set-tok", "enabled": False})
        assert DiscordConfig.load() is None


class TestSlackConfig:
    def test_none_without_any_config(self, monkeypatch, tmp_db):
        monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
        _seed_settings(monkeypatch, "slack", None)
        assert SlackConfig.load() is None

    def test_settings_string_channel_ids(self, monkeypatch, tmp_db):
        monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
        _seed_settings(
            monkeypatch,
            "slack",
            {"bot_token": "set-tok", "allowed_channel_ids": "C1, C2"},
        )
        cfg = SlackConfig.load()
        assert cfg is not None
        assert cfg.allowed_channel_ids == ["C1", "C2"]

    def test_settings_disabled_wins_over_env(self, monkeypatch, tmp_db):
        monkeypatch.setenv("SLACK_BOT_TOKEN", "env-tok")
        _seed_settings(monkeypatch, "slack", {"bot_token": "set-tok", "enabled": False})
        assert SlackConfig.load() is None


# --------------------------------------------------------------------------- #
# fetch_updates：游标 + 自环防护
# --------------------------------------------------------------------------- #


class TestDiscordFetchUpdates:
    def test_first_sight_advances_cursor_without_replay(self, tmp_db):
        gateway, transport = _discord_gateway(tmp_db)
        transport.pages["111111"] = [
            {"id": "10", "content": "旧消息", "author": {"name": "a"}},
            {"id": "11", "content": "新消息", "author": {"name": "a"}},
        ]
        updates = gateway.fetch_updates()
        assert updates == []  # 首见不回放
        assert gateway._last_message_id["111111"] == "11"

    def test_after_cursor_emits_new_messages_only(self, tmp_db):
        gateway, transport = _discord_gateway(tmp_db)
        gateway._last_message_id["111111"] = "10"
        transport.pages["111111"] = [
            {"id": "11", "content": "你好", "author": {"name": "a"}},
        ]
        updates = gateway.fetch_updates()
        assert len(updates) == 1
        assert updates[0]["channel_id"] == "111111"
        assert updates[0]["content"] == "你好"
        assert updates[0]["message_id"] == 11

    def test_bot_messages_skipped_but_cursor_advances(self, tmp_db):
        gateway, transport = _discord_gateway(tmp_db)
        gateway._last_message_id["111111"] = "10"
        transport.pages["111111"] = [
            {"id": "11", "content": "我是机器人", "author": {"bot": True, "name": "sage"}},
            {"id": "12", "content": "真人消息", "author": {"name": "a"}},
        ]
        updates = gateway.fetch_updates()
        assert [u["content"] for u in updates] == ["真人消息"]
        assert gateway._last_message_id["111111"] == "12"

    def test_multi_channel_isolation(self, tmp_db):
        gateway, transport = _discord_gateway(tmp_db, allowed=("111", "222"))
        gateway._last_message_id = {"111": "10", "222": "20"}
        transport.pages = {
            "111": [{"id": "11", "content": "c1", "author": {}}],
            "222": [{"id": "21", "content": "c2", "author": {}}],
        }
        updates = gateway.fetch_updates()
        assert {(u["channel_id"], u["content"]) for u in updates} == {
            ("111", "c1"),
            ("222", "c2"),
        }

    def test_channel_error_does_not_break_others(self, tmp_db):
        gateway, transport = _discord_gateway(tmp_db, allowed=("111", "222"))
        gateway._last_message_id = {"111": "10", "222": "20"}

        def boom(channel_id, after_id, limit):
            if channel_id == "111":
                raise RuntimeError("down")
            return [{"id": "21", "content": "c2", "author": {}}]

        transport.fetch_messages = boom
        updates = gateway.fetch_updates()
        assert [u["channel_id"] for u in updates] == ["222"]
        assert gateway.stats.errors == 1

    def test_parse_update_envelope(self, tmp_db):
        gateway, _ = _discord_gateway(tmp_db)
        assert gateway.parse_update({"channel_id": "111", "content": " hi "}) == ("111", "hi")
        assert gateway.parse_update({"channel_id": "", "content": "x"}) is None
        assert gateway.parse_update({"channel_id": "111", "content": ""}) is None


class TestSlackFetchUpdates:
    def test_first_sight_advances_cursor_without_replay(self, tmp_db):
        gateway, transport = _slack_gateway(tmp_db)
        transport.pages["C111"] = [
            {"ts": "1726000000.000200", "text": "新消息", "user": "u1"},
            {"ts": "1726000000.000100", "text": "旧消息", "user": "u1"},
        ]
        updates = gateway.fetch_updates()
        assert updates == []
        assert gateway._last_ts["C111"] == "1726000000.000200"

    def test_after_cursor_emits_new_messages_in_order(self, tmp_db):
        gateway, transport = _slack_gateway(tmp_db)
        gateway._last_ts["C111"] = "1726000000.000100"
        # API 返回新→旧
        transport.pages["C111"] = [
            {"ts": "1726000000.000300", "text": "b", "user": "u1"},
            {"ts": "1726000000.000200", "text": "a", "user": "u1"},
        ]
        updates = gateway.fetch_updates()
        assert [(u["text"]) for u in updates] == ["a", "b"]  # 旧→新 emit

    def test_bot_and_subtype_skipped(self, tmp_db):
        gateway, transport = _slack_gateway(tmp_db)
        gateway._last_ts["C111"] = "1726000000.000000"
        transport.pages["C111"] = [
            {"ts": "1726000000.000001", "text": "bot", "bot_id": "B1"},
            {"ts": "1726000000.000002", "text": "join", "subtype": "channel_join"},
            {"ts": "1726000000.000003", "text": "真人", "user": "u1"},
        ]
        updates = gateway.fetch_updates()
        assert [u["text"] for u in updates] == ["真人"]

    def test_channel_error_does_not_break_others(self, tmp_db):
        gateway, transport = _slack_gateway(tmp_db, allowed=("C1", "C2"))
        gateway._last_ts = {"C1": "1", "C2": "1"}

        def boom(channel_id, oldest, limit):
            if channel_id == "C1":
                raise RuntimeError("down")
            return [{"ts": "1726000000.000100", "text": "ok", "user": "u1"}]

        transport.fetch_history = boom
        updates = gateway.fetch_updates()
        assert [u["channel_id"] for u in updates] == ["C2"]
        assert gateway.stats.errors == 1


# --------------------------------------------------------------------------- #
# 白名单 + 全链路对话
# --------------------------------------------------------------------------- #


class TestDiscordConversationFlow:
    def test_unauthorized_channel_rejected(self, tmp_db):
        gateway, transport = _discord_gateway(tmp_db, allowed=("111",))
        gateway.handle_update(
            {"message_id": 12, "channel_id": "999", "content": "hi", "author": {}}
        )
        assert transport.sent
        assert "未授权" in transport.sent[0][1]
        assert gateway.stats.rejected == 1

    def test_authorized_channel_gets_llm_reply(self, tmp_db):
        gateway, transport = _discord_gateway(tmp_db, allowed=("111",))
        gateway.handle_update(
            {"message_id": 12, "channel_id": "111", "content": "你好", "author": {}}
        )
        assert transport.sent == [("111", "回复")]
        assert gateway.stats.messages_replied == 1

    def test_bound_session_reused(self, tmp_db):
        gateway, _ = _discord_gateway(tmp_db, allowed=("111",))
        gateway.handle_update(
            {"message_id": 12, "channel_id": "111", "content": "一", "author": {}}
        )
        gateway.handle_update(
            {"message_id": 13, "channel_id": "111", "content": "二", "author": {}}
        )
        rows = (
            tmp_db.get_connection()
            .execute("SELECT COUNT(*) FROM gateway_binds WHERE chat_id = '111'")
            .fetchone()
        )
        assert rows[0] == 1


class TestSlackConversationFlow:
    def test_unauthorized_channel_rejected(self, tmp_db):
        gateway, transport = _slack_gateway(tmp_db, allowed=("C111",))
        gateway.handle_update({"event_ts": 2, "channel_id": "C999", "text": "hi"})
        assert transport.sent
        assert "未授权" in transport.sent[0][1]

    def test_authorized_channel_gets_llm_reply(self, tmp_db):
        gateway, transport = _slack_gateway(tmp_db, allowed=("C111",))
        gateway.handle_update({"event_ts": 2, "channel_id": "C111", "text": "你好"})
        assert transport.sent == [("C111", "回复")]


# --------------------------------------------------------------------------- #
# transport 截断
# --------------------------------------------------------------------------- #


class TestTransportTruncation:
    def test_discord_transport_truncates_to_2000(self, monkeypatch):
        captured = {}

        class _Resp:
            def raise_for_status(self):
                return None

        def _fake_post(url, json=None, headers=None, timeout=None):
            captured["json"] = json
            return _Resp()

        import httpx

        monkeypatch.setattr(httpx, "post", _fake_post)
        DiscordTransport("tok").send_message("111", "x" * 3000)
        assert len(captured["json"]["content"]) == 2000

    def test_slack_transport_truncates_to_4000(self, monkeypatch):
        captured = {}

        class _Resp:
            def raise_for_status(self):
                return None

            def json(self):
                return {"ok": True}

        def _fake_post(url, json=None, headers=None, timeout=None):
            captured["json"] = json
            return _Resp()

        import httpx

        monkeypatch.setattr(httpx, "post", _fake_post)
        SlackTransport("xoxb-tok").post_message("C1", "x" * 5000)
        assert len(captured["json"]["text"]) == 4000


# --------------------------------------------------------------------------- #
# 路由：status + config
# --------------------------------------------------------------------------- #


class TestGatewayRoutes:
    def test_discord_status_not_configured(self, monkeypatch, client, tmp_db):
        monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
        _seed_settings(monkeypatch, "discord", None)
        resp = client.get("/gateway/discord/status")
        assert resp.status_code == 200
        assert resp.json()["configured"] is False

    def test_slack_status_not_configured(self, monkeypatch, client, tmp_db):
        monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
        _seed_settings(monkeypatch, "slack", None)
        resp = client.get("/gateway/slack/status")
        assert resp.status_code == 200
        assert resp.json()["configured"] is False

    def test_discord_config_masked_and_saved(self, monkeypatch, client, tmp_db):
        monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
        _seed_settings(
            monkeypatch,
            "discord",
            {"bot_token": "1234567890abcdefgh", "allowed_channel_ids": ["42"]},
        )
        resp = client.get("/gateway/discord/config")
        assert resp.status_code == 200
        data = resp.json()
        assert data["source"] == "settings"
        assert data["bot_token_masked"].startswith("****")
        assert "abcdefgh" not in data["bot_token_masked"]

    def test_slack_config_put_saves_settings(self, monkeypatch, client, tmp_db):
        monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
        saved = _seed_settings(monkeypatch, "slack", None)
        resp = client.put(
            "/gateway/slack/config",
            json={"bot_token": "new-tok", "allowed_channel_ids": ["C7"], "enabled": True},
        )
        assert resp.status_code == 200
        assert resp.json() == {"saved": True, "restart_required": True}
        assert saved["app_settings"]["slack"]["bot_token"] == "new-tok"
        assert saved["app_settings"]["slack"]["allowed_channel_ids"] == ["C7"]


# --------------------------------------------------------------------------- #
# token 保留契约（打码回传 ≠ 清除）
# --------------------------------------------------------------------------- #


class TestTokenPreserveContract:
    def test_telegram_masked_token_keeps_stored(self, monkeypatch, client, tmp_db):
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        _seed_settings(
            monkeypatch,
            "telegram",
            {"bot_token": "real-token", "allowed_chat_ids": ["1"], "enabled": True},
        )
        resp = client.put(
            "/gateway/telegram/config",
            json={"bot_token": "****token", "allowed_chat_ids": ["1", "2"], "enabled": True},
        )
        assert resp.status_code == 200
        # 回读：真实 token 保留，白名单已更新
        view = client.get("/gateway/telegram/config").json()
        assert view["bot_token_masked"] == "****oken"  # real-token 尾 4 位
        assert view["allowed_chat_ids"] == ["1", "2"]

    def test_telegram_empty_token_clears(self, monkeypatch, client, tmp_db):
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        _seed_settings(
            monkeypatch,
            "telegram",
            {"bot_token": "real-token", "allowed_chat_ids": ["1"], "enabled": True},
        )
        resp = client.put(
            "/gateway/telegram/config",
            json={"bot_token": "", "allowed_chat_ids": ["1"], "enabled": False},
        )
        assert resp.status_code == 200
        view = client.get("/gateway/telegram/config").json()
        assert view["configured"] is False

    def test_discord_masked_token_keeps_stored(self, monkeypatch, client, tmp_db):
        monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
        _seed_settings(
            monkeypatch,
            "discord",
            {"bot_token": "real-discord", "allowed_channel_ids": ["42"], "enabled": True},
        )
        resp = client.put(
            "/gateway/discord/config",
            json={"bot_token": "****cord", "allowed_channel_ids": ["42"], "enabled": True},
        )
        assert resp.status_code == 200
        view = client.get("/gateway/discord/config").json()
        assert view["bot_token_masked"].endswith("cord")
        assert view["configured"] is True


# --------------------------------------------------------------------------- #
# binds 路由（discord / slack）
# --------------------------------------------------------------------------- #


class TestPlatformBindsRoutes:
    def test_discord_binds_503_when_unconfigured(self, monkeypatch, client, tmp_db):
        monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
        _seed_settings(monkeypatch, "discord", None)
        resp = client.get("/gateway/discord/binds")
        assert resp.status_code == 503
        assert resp.json()["detail"]["type"] == "gateway_disabled"

    def test_slack_unbind_404_when_gateway_alive_but_no_bind(self, monkeypatch, client, tmp_db):
        import backend.gateway.slack as slack_mod

        monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
        _seed_settings(monkeypatch, "slack", None)
        gateway, _ = _slack_gateway(tmp_db, allowed=("C111",))
        monkeypatch.setattr(slack_mod, "get_slack_gateway", lambda: gateway)
        resp = client.delete("/gateway/slack/binds/C999")
        assert resp.status_code == 404
        assert resp.json()["detail"]["type"] == "bind_not_found"

    def test_discord_binds_lists_and_unbinds(self, monkeypatch, client, tmp_db):
        import backend.gateway.discord as discord_mod

        monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
        _seed_settings(monkeypatch, "discord", None)
        gateway, _ = _discord_gateway(tmp_db, allowed=("111",))
        conn = tmp_db.get_connection()
        conn.execute(
            "INSERT INTO gateway_binds (chat_id, session_id, created_at) VALUES (?, ?, ?)",
            ("111", "sess-1", 123),
        )
        conn.commit()
        monkeypatch.setattr(discord_mod, "get_discord_gateway", lambda: gateway)

        listed = client.get("/gateway/discord/binds").json()
        assert listed["binds"][0]["chat_id"] == "111"

        removed = client.delete("/gateway/discord/binds/111").json()
        assert removed == {"chat_id": "111", "unbound": True}
