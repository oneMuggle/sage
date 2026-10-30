"""scripts/feedback_receiver.py — 中继 + 转发脚本的行为契约测试。

两层覆盖：
1) Relay / Store 逻辑层（不起 HTTP，直接断言落库与幂等）；
2) HTTP 层（在 127.0.0.1:0 上起真服务，用 http.client 走真请求），
   重点锁住桌面端 FeedbackSyncer 依赖的契约：GET 回复必须是裸 JSON 数组。

CI 不跑 scripts/tests（ci.yml 只跑 backend/），提交前需手动执行：
    /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest scripts/tests/test_feedback_receiver.py
"""

import base64
import contextlib
import http.client
import json
import sys
import threading
import time
import urllib.parse
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))

import feedback_receiver  # noqa: E402

SECRET = "sekret"
ADMIN_PASSWORD = "pw"
WEBHOOK_TOKEN = "hooktok"


# ==========================================================================
# 工具
# ==========================================================================


def payload(message_id="m-1", body="导出后中文变乱码", **overrides):
    """桌面端 FeedbackSyncer.submitConversation() 实际发来的 payload 形状。"""
    base = {
        "id": message_id,
        "role": "user",
        "body": body,
        "media_ids": [],
        "created_at": 1761700000000,
        "title": "导出乱码",
        "app_version": "0.4.9",
        "os_info": "linux",
        "conversation_created_at": 1761700000000,
    }
    base.update(overrides)
    return base


def wait_until(predicate, timeout=5.0):
    """转发在 daemon 线程里跑，只能轮询等待。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


class RecordingForwarder(feedback_receiver.Forwarder):
    name = "recording"

    def __init__(self):
        self.tickets = []
        self.comments = []

    def is_enabled(self):
        return True

    def create_ticket(self, conv, body):
        self.tickets.append((conv["id"], conv["title"], body))
        return "T-1", "http://tracker/T-1"

    def add_comment(self, conv, body):
        self.comments.append((conv["id"], body))


@contextlib.contextmanager
def running_server(tmp_path, **overrides):
    options = dict(
        shared_secret=SECRET,
        data_dir=tmp_path / ("data-" + uuid.uuid4().hex[:8]),
        listen_host="127.0.0.1",
        listen_port=0,
        admin_user="admin",
        admin_password=ADMIN_PASSWORD,
        webhook_token=WEBHOOK_TOKEN,
    )
    options.update(overrides)
    config = feedback_receiver.Config(**options)
    server = feedback_receiver.build_server(
        config, forwarder=feedback_receiver.Forwarder()
    )
    thread = threading.Thread(target=server.serve_forever, args=(0.05,), daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def call(server, method, path, body=None, headers=None):
    port = server.server_address[1]
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.request(method, path, body=body, headers=headers or {})
        response = conn.getresponse()
        raw = response.read()
        return response.status, dict(response.getheaders()), raw
    finally:
        conn.close()


def bearer_headers():
    return {"Authorization": "Bearer " + SECRET, "Content-Type": "application/json"}


def admin_headers():
    raw = "admin:{}".format(ADMIN_PASSWORD).encode("utf-8")
    return {"Authorization": "Basic " + base64.b64encode(raw).decode("ascii")}


@pytest.fixture
def store(tmp_path):
    return feedback_receiver.Store(tmp_path / "feedback.db", tmp_path / "attachments")


@pytest.fixture
def relay(store):
    return feedback_receiver.Relay(store)


@pytest.fixture
def server(tmp_path):
    with running_server(tmp_path) as instance:
        yield instance


# ==========================================================================
# 配置
# ==========================================================================


class TestConfig:
    def test_missing_shared_secret_is_fatal(self):
        with pytest.raises(SystemExit):
            feedback_receiver.Config.from_env({})

    def test_defaults(self):
        config = feedback_receiver.Config.from_env({"FEEDBACK_SHARED_SECRET": SECRET})
        assert config.listen_port == feedback_receiver.DEFAULT_PORT
        assert config.listen_host == "127.0.0.1"
        assert config.admin_user == "admin"
        assert config.admin_password == ""
        assert config.webhook_token == ""

    def test_env_overrides(self):
        config = feedback_receiver.Config.from_env(
            {
                "FEEDBACK_SHARED_SECRET": SECRET,
                "FEEDBACK_LISTEN_PORT": "9999",
                "FEEDBACK_ADMIN_PASSWORD": "pw",
                "FEEDBACK_DATA_DIR": "/tmp/x",
            }
        )
        assert config.listen_port == 9999
        assert config.admin_password == "pw"
        assert str(config.data_dir) == "/tmp/x"


class TestBuildForwarder:
    def test_defaults_to_noop(self):
        assert feedback_receiver.build_forwarder({}).name == "none"

    def test_jira_wins_over_gitlab_and_smtp(self):
        forwarder = feedback_receiver.build_forwarder(
            {
                "FEEDBACK_JIRA_URL": "http://jira",
                "FEEDBACK_JIRA_TOKEN": "t",
                "FEEDBACK_JIRA_PROJECT": "PROJ",
                "FEEDBACK_GITLAB_URL": "http://gitlab",
                "FEEDBACK_GITLAB_TOKEN": "t",
                "FEEDBACK_GITLAB_PROJECT": "g/p",
            }
        )
        assert forwarder.name == "jira"

    def test_gitlab_used_when_jira_incomplete(self):
        forwarder = feedback_receiver.build_forwarder(
            {
                "FEEDBACK_JIRA_URL": "http://jira",
                "FEEDBACK_GITLAB_URL": "http://gitlab",
                "FEEDBACK_GITLAB_TOKEN": "t",
                "FEEDBACK_GITLAB_PROJECT": "g/p",
            }
        )
        assert forwarder.name == "gitlab"

    def test_smtp_used_when_nothing_else(self):
        forwarder = feedback_receiver.build_forwarder(
            {
                "FEEDBACK_SMTP_HOST": "mail",
                "FEEDBACK_SMTP_FROM": "a@b.c",
                "FEEDBACK_SMTP_TO": "d@e.f",
            }
        )
        assert forwarder.name == "smtp"


# ==========================================================================
# 逻辑层：落库 / 幂等
# ==========================================================================


class TestIngest:
    def test_first_message_creates_conversation(self, relay, store):
        result = relay.ingest_user_message("c-1", payload(), "client-1")

        assert result == {"received": True, "duplicate": False}
        conv = store.get_conversation("c-1")
        assert conv is not None
        assert conv["title"] == "导出乱码"
        assert conv["app_version"] == "0.4.9"
        assert conv["os_info"] == "linux"
        assert conv["client_id"] == "client-1"
        assert conv["status"] == "open"

        messages = store.list_messages("c-1")
        assert [m["id"] for m in messages] == ["m-1"]
        assert messages[0]["origin"] == "client"

    def test_duplicate_message_id_is_idempotent(self, relay, store):
        relay.ingest_user_message("c-1", payload(), "client-1")
        second = relay.ingest_user_message("c-1", payload(), "client-1")

        assert second == {"received": True, "duplicate": True}
        assert len(store.list_messages("c-1")) == 1

    def test_missing_title_falls_back(self, relay, store):
        relay.ingest_user_message("c-1", payload(title=""), "client-1")
        assert store.get_conversation("c-1")["title"] == "未命名反馈"

    def test_media_ids_round_trip(self, relay, store):
        relay.ingest_user_message(
            "c-1", payload(media_ids=["m-abc", "m-def"]), "client-1"
        )
        stored = json.loads(store.list_messages("c-1")[0]["media_ids"])
        assert stored == ["m-abc", "m-def"]

    def test_second_message_updates_activity(self, relay, store):
        relay.ingest_user_message("c-1", payload(), "client-1")
        before = store.get_conversation("c-1")["updated_at"]
        relay.ingest_user_message("c-1", payload("m-2", body="补充说明"), "client-1")
        assert store.get_conversation("c-1")["updated_at"] >= before
        assert len(store.list_messages("c-1")) == 2


class TestForwarding:
    def test_ticket_created_for_new_conversation(self, store):
        forwarder = RecordingForwarder()
        relay = feedback_receiver.Relay(store, forwarder)

        relay.ingest_user_message("c-1", payload(), "client-1")

        assert wait_until(
            lambda: store.get_conversation("c-1")["remote_ticket_id"] == "T-1"
        )
        conv = store.get_conversation("c-1")
        assert conv["remote_system"] == "recording"
        assert conv["remote_ticket_url"] == "http://tracker/T-1"
        assert forwarder.tickets == [
            ("c-1", "导出乱码", "[1761700000000] 导出后中文变乱码")
        ]

    def test_subsequent_message_becomes_comment(self, store):
        forwarder = RecordingForwarder()
        relay = feedback_receiver.Relay(store, forwarder)

        relay.ingest_user_message("c-1", payload(), "client-1")
        assert wait_until(
            lambda: store.get_conversation("c-1")["remote_ticket_id"] == "T-1"
        )
        relay.ingest_user_message("c-1", payload("m-2", body="补充"), "client-1")

        assert wait_until(lambda: len(forwarder.comments) == 1)
        assert forwarder.comments[0][0] == "c-1"
        assert "补充" in forwarder.comments[0][1]
        assert len(forwarder.tickets) == 1  # 没有建第二张工单

    def test_forwarder_failure_does_not_lose_message(self, store):
        class ExplodingForwarder(RecordingForwarder):
            def create_ticket(self, conv, body):
                raise RuntimeError("tracker down")

        relay = feedback_receiver.Relay(store, ExplodingForwarder())
        relay.ingest_user_message("c-1", payload(), "client-1")

        assert len(store.list_messages("c-1")) == 1
        assert store.get_conversation("c-1")["remote_ticket_id"] is None


# ==========================================================================
# 逻辑层：webhook 回流
# ==========================================================================


class TestWebhooks:
    def setup_conversation(self, relay, store, system="jira", ticket_id="PROJ-1"):
        relay.ingest_user_message("c-1", payload(), "client-1")
        store.set_remote_ticket("c-1", system, ticket_id, "http://tracker/" + ticket_id)

    def test_jira_comment_becomes_admin_message(self, relay, store):
        self.setup_conversation(relay, store)

        result = relay.handle_jira_webhook(
            {
                "webhookEvent": "comment_created",
                "issue": {"key": "PROJ-1"},
                "comment": {"body": "已复现，正在修", "created": "2026-10-29T10:00:00Z"},
            }
        )

        assert result["stored"] is True
        replies = relay.replies_since("c-1", 0)
        assert [r["body"] for r in replies] == ["已复现，正在修"]
        assert replies[0]["role"] == "admin"
        assert store.list_messages("c-1", roles=("admin",))[0]["origin"] == "jira"

    def test_jira_ignores_other_events(self, relay, store):
        self.setup_conversation(relay, store)
        result = relay.handle_jira_webhook(
            {"webhookEvent": "issue_created", "issue": {"key": "PROJ-1"}}
        )
        assert result["stored"] is False
        assert relay.replies_since("c-1", 0) == []

    def test_jira_unknown_ticket_is_not_stored(self, relay, store):
        self.setup_conversation(relay, store)
        result = relay.handle_jira_webhook(
            {
                "webhookEvent": "comment_created",
                "issue": {"key": "OTHER-9"},
                "comment": {"body": "hi"},
            }
        )
        assert result["stored"] is False
        assert relay.replies_since("c-1", 0) == []

    def test_gitlab_note_becomes_admin_message(self, relay, store):
        self.setup_conversation(relay, store, system="gitlab", ticket_id="12")

        result = relay.handle_gitlab_webhook(
            {
                "object_kind": "note",
                "issue": {"iid": 12},
                "object_attributes": {
                    "note": "下周发版修复",
                    "created_at": "2026-10-29 10:00:00 UTC",
                },
            }
        )

        assert result["stored"] is True
        assert [r["body"] for r in relay.replies_since("c-1", 0)] == ["下周发版修复"]

    def test_gitlab_ignores_non_note_events(self, relay, store):
        self.setup_conversation(relay, store, system="gitlab", ticket_id="12")
        result = relay.handle_gitlab_webhook(
            {"object_kind": "issue", "issue": {"iid": 12}}
        )
        assert result["stored"] is False

    def test_empty_body_is_not_stored(self, relay, store):
        self.setup_conversation(relay, store)
        result = relay.handle_jira_webhook(
            {
                "webhookEvent": "comment_created",
                "issue": {"key": "PROJ-1"},
                "comment": {"body": "   "},
            }
        )
        assert result["stored"] is False


class TestRepliesSince:
    def test_only_admin_messages_after_since(self, relay, store):
        relay.ingest_user_message("c-1", payload(created_at=1000), "client-1")
        first = relay.add_admin_message("c-1", "第一条回复", origin="admin-page")
        second = relay.add_admin_message("c-1", "第二条回复", origin="admin-page")
        assert first and second

        rows = {r["id"]: r for r in store.list_messages("c-1", roles=("admin",))}
        latest = max(r["created_at"] for r in rows.values())

        assert relay.replies_since("c-1", 0) != []
        assert relay.replies_since("c-1", latest) == []

    def test_reply_shape_matches_client_contract(self, relay):
        relay.ingest_user_message("c-1", payload(), "client-1")
        relay.add_admin_message("c-1", "已复现", origin="admin-page")
        reply = relay.replies_since("c-1", 0)[0]
        assert set(reply) == {"id", "role", "body", "created_at"}
        assert isinstance(reply["created_at"], int)

    def test_blank_admin_reply_is_rejected(self, relay):
        relay.ingest_user_message("c-1", payload(), "client-1")
        assert relay.add_admin_message("c-1", "   ", origin="admin-page") is None


# ==========================================================================
# 存储：附件
# ==========================================================================


class TestAttachments:
    def test_save_and_read(self, store):
        store.save_attachment("m-1", "c-1", b"\x89PNG-bytes", "image/png")
        assert store.get_attachment("m-1")["size_bytes"] == len(b"\x89PNG-bytes")
        assert store.attachment_path("m-1").read_bytes() == b"\x89PNG-bytes"

    @pytest.mark.parametrize("media_id", ["../evil", "a/b", "", "x" * 129, "a b"])
    def test_rejects_unsafe_media_id(self, store, media_id):
        with pytest.raises(ValueError):
            store.save_attachment(media_id, "c-1", b"x", "text/plain")


# ==========================================================================
# HTTP 层
# ==========================================================================


class TestHttpAuth:
    def test_health_needs_no_auth(self, server):
        status, _headers, body = call(server, "GET", "/api/v1/feedback/health")
        assert status == 200
        assert json.loads(body)["status"] == "ok"

    def test_ingest_without_bearer_is_401(self, server):
        status, _headers, _body = call(
            server,
            "POST",
            "/api/v1/feedback/conversations/c-1/messages",
            body=json.dumps(payload()),
            headers={"Content-Type": "application/json"},
        )
        assert status == 401

    def test_ingest_with_wrong_secret_is_401(self, server):
        status, _headers, _body = call(
            server,
            "POST",
            "/api/v1/feedback/conversations/c-1/messages",
            body=json.dumps(payload()),
            headers={
                "Authorization": "Bearer wrong",
                "Content-Type": "application/json",
            },
        )
        assert status == 401

    def test_admin_page_requires_basic_auth(self, server):
        status, headers, _body = call(server, "GET", "/")
        assert status == 401
        assert "Basic" in headers.get("WWW-Authenticate", "")

    def test_admin_page_disabled_without_password(self, tmp_path):
        with running_server(tmp_path, admin_password="") as instance:
            status, _headers, _body = call(instance, "GET", "/")
        assert status == 404

    def test_webhook_disabled_returns_404(self, tmp_path):
        with running_server(tmp_path, webhook_token="") as instance:
            status, _headers, _body = call(
                instance,
                "POST",
                "/api/v1/webhooks/jira",
                body=json.dumps({"webhookEvent": "comment_created"}),
                headers={"Content-Type": "application/json"},
            )
        assert status == 404

    def test_webhook_requires_token(self, server):
        status, _headers, _body = call(
            server,
            "POST",
            "/api/v1/webhooks/jira",
            body=json.dumps({"webhookEvent": "comment_created"}),
            headers={"Content-Type": "application/json"},
        )
        assert status == 401


class TestHttpFlow:
    def test_ingest_then_reply_round_trip(self, server):
        """桌面端完整闭环：POST 消息 → 管理页回复 → GET 拿到裸数组。"""
        status, _headers, body = call(
            server,
            "POST",
            "/api/v1/feedback/conversations/c-1/messages",
            body=json.dumps(payload()),
            headers=bearer_headers(),
        )
        assert status == 200
        assert json.loads(body) == {"received": True, "duplicate": False}

        # 还没有管理员回复 → 必须是空数组，不是 {"messages": []}
        status, _headers, body = call(
            server,
            "GET",
            "/api/v1/feedback/conversations/c-1/messages?since=0",
            headers=bearer_headers(),
        )
        assert status == 200
        assert json.loads(body) == []

        status, headers, _body = call(
            server,
            "POST",
            "/conversation/c-1/reply",
            body=urllib.parse.urlencode({"body": "已复现，正在修"}).encode("utf-8"),
            headers=dict(
                admin_headers(),
                **{"Content-Type": "application/x-www-form-urlencoded"},
            ),
        )
        assert status == 303
        assert headers["Location"] == "/conversation/c-1"

        status, _headers, body = call(
            server,
            "GET",
            "/api/v1/feedback/conversations/c-1/messages?since=0",
            headers=bearer_headers(),
        )
        assert status == 200
        replies = json.loads(body)
        assert len(replies) == 1
        assert set(replies[0]) == {"id", "role", "body", "created_at"}
        assert replies[0]["role"] == "admin"
        assert replies[0]["body"] == "已复现，正在修"

        # since = 该回复时间戳 → 不再返回它（客户端据此避免重复写入）
        status, _headers, body = call(
            server,
            "GET",
            "/api/v1/feedback/conversations/c-1/messages?since={}".format(
                replies[0]["created_at"]
            ),
            headers=bearer_headers(),
        )
        assert json.loads(body) == []

    def test_duplicate_ingest_is_reported(self, server):
        for expected_duplicate in (False, True):
            status, _headers, body = call(
                server,
                "POST",
                "/api/v1/feedback/conversations/c-1/messages",
                body=json.dumps(payload()),
                headers=bearer_headers(),
            )
            assert status == 200
            assert json.loads(body)["duplicate"] is expected_duplicate

    def test_ingest_rejects_missing_fields(self, server):
        status, _headers, _body = call(
            server,
            "POST",
            "/api/v1/feedback/conversations/c-1/messages",
            body=json.dumps({"id": "m-1"}),
            headers=bearer_headers(),
        )
        assert status == 400

    def test_ingest_rejects_bad_conversation_id(self, server):
        status, _headers, _body = call(
            server,
            "POST",
            "/api/v1/feedback/conversations/..%2Fevil/messages",
            body=json.dumps(payload()),
            headers=bearer_headers(),
        )
        assert status == 400

    def test_admin_list_and_detail_render(self, server):
        call(
            server,
            "POST",
            "/api/v1/feedback/conversations/c-1/messages",
            body=json.dumps(payload()),
            headers=bearer_headers(),
        )
        call(
            server,
            "POST",
            "/api/v1/feedback/conversations/c-1/messages",
            body=json.dumps(payload("m-2", body="<script>alert(1)</script>")),
            headers=bearer_headers(),
        )

        status, _headers, body = call(server, "GET", "/", headers=admin_headers())
        assert status == 200
        assert "导出乱码" in body.decode("utf-8")

        status, _headers, body = call(
            server, "GET", "/conversation/c-1", headers=admin_headers()
        )
        assert status == 200
        markup = body.decode("utf-8")
        assert "导出后中文变乱码" in markup
        # 用户内容必须转义，不能原样注入
        assert "<script>alert(1)</script>" not in markup
        assert "&lt;script&gt;" in markup

    def test_attachment_upload_and_download(self, server):
        call(
            server,
            "POST",
            "/api/v1/feedback/conversations/c-1/messages",
            body=json.dumps(payload(media_ids=["m-abc"])),
            headers=bearer_headers(),
        )

        raw = b"\x89PNG\r\n\x1a\nfake"
        status, _headers, _body = call(
            server,
            "POST",
            "/api/v1/feedback/conversations/c-1/attachments/m-abc",
            body=raw,
            headers={
                "Authorization": "Bearer " + SECRET,
                "Content-Type": "image/png",
            },
        )
        assert status == 200

        status, headers, body = call(
            server,
            "GET",
            "/api/v1/feedback/attachments/m-abc",
            headers=bearer_headers(),
        )
        assert status == 200
        assert headers["Content-Type"] == "image/png"
        assert body == raw

    def test_attachment_upload_rejects_traversal(self, server):
        status, _headers, _body = call(
            server,
            "POST",
            "/api/v1/feedback/conversations/c-1/attachments/..%2Fevil",
            body=b"data",
            headers={
                "Authorization": "Bearer " + SECRET,
                "Content-Type": "text/plain",
            },
        )
        assert status == 400

    def test_unknown_route_is_404(self, server):
        status, _headers, _body = call(server, "GET", "/nope", headers=admin_headers())
        assert status == 404

    def test_webhook_via_http_stores_reply(self, server):
        call(
            server,
            "POST",
            "/api/v1/feedback/conversations/c-1/messages",
            body=json.dumps(payload()),
            headers=bearer_headers(),
        )
        # 手工把工单号写回（真实流程里由转发线程完成）
        store = server.RequestHandlerClass.relay.store
        store.set_remote_ticket("c-1", "jira", "PROJ-1", "http://jira/browse/PROJ-1")

        status, _headers, body = call(
            server,
            "POST",
            "/api/v1/webhooks/jira?token=" + WEBHOOK_TOKEN,
            body=json.dumps(
                {
                    "webhookEvent": "comment_created",
                    "issue": {"key": "PROJ-1"},
                    "comment": {"body": "收到，正在排查"},
                }
            ),
            headers={"Content-Type": "application/json"},
        )
        assert status == 200
        assert json.loads(body)["stored"] is True

        status, _headers, body = call(
            server,
            "GET",
            "/api/v1/feedback/conversations/c-1/messages?since=0",
            headers=bearer_headers(),
        )
        assert [r["body"] for r in json.loads(body)] == ["收到，正在排查"]
