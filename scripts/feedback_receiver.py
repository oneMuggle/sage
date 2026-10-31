#!/usr/bin/env python3
"""Sage 用户反馈转发脚本（管理员侧，单文件、零第三方依赖）。

单文件是刻意的部署目标：把它拷到任意一台有 Python 3.8+ 的机器上就能跑，
不需要 virtualenv，不需要 pip install。

它同时扮演两个角色：

  1. 中继：接收 Sage 桌面端提交的会话消息，落本地 SQLite；
  2. 转发：把新会话/新消息推到 Jira、GitLab 或邮件；把管理员那边的回复
     （Jira/GitLab webhook 或自带管理页）回流给桌面端轮询。

数据流：

    桌面端 FeedbackSyncer ──POST /api/v1/feedback/conversations/{id}/messages──▶ 本脚本
    桌面端 FeedbackSyncer ──GET  .../messages?since=<ms>──────────────────────▶ 本脚本
    Jira / GitLab ────────POST /api/v1/webhooks/{jira,gitlab}─────────────────▶ 本脚本
    管理员浏览器 ──────────GET / , POST /conversation/{id}/reply──────────────▶ 本脚本

桌面端只信任"2xx 就算送达"，所以落库先于转发：即使 Jira 挂了，消息也不会丢，
管理员仍能在管理页看到并回复。

启动示例：

    export FEEDBACK_SHARED_SECRET="$(python3 -c 'import secrets;print(secrets.token_urlsafe(32))')"
    export FEEDBACK_ADMIN_PASSWORD="change-me"
    python3 scripts/feedback_receiver.py

<<<<<<< HEAD
完整部署说明见 docs/technical/111-feedback-relay-deployment.md。
=======
完整部署说明见 docs/technical/109-feedback-relay-deployment.md。
>>>>>>> origin/main
"""

from __future__ import annotations

import base64
import contextlib
import dataclasses
import hmac
import html
import json
import logging
import os
import re
import smtplib
import sqlite3
import sys
import threading
import time
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from email.message import EmailMessage
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

LOG = logging.getLogger("feedback_relay")

DEFAULT_PORT = 8900
DEFAULT_MAX_BODY_BYTES = 8 * 1024 * 1024
HTTP_TIMEOUT_S = 15

# media_id 会直接拼进文件路径，必须先过白名单再落盘（防路径穿越）。
MEDIA_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
CONVERSATION_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")

SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    client_id TEXT,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    app_version TEXT NOT NULL DEFAULT '',
    os_info TEXT NOT NULL DEFAULT '',
    remote_system TEXT,
    remote_ticket_id TEXT,
    remote_ticket_url TEXT,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('user', 'admin')),
    body TEXT NOT NULL,
    media_ids TEXT NOT NULL DEFAULT '[]',
    origin TEXT NOT NULL DEFAULT 'client',
    created_at INTEGER NOT NULL,
    FOREIGN KEY(conversation_id) REFERENCES conversations(id)
);

CREATE TABLE IF NOT EXISTS attachments (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    mime_type TEXT NOT NULL DEFAULT 'application/octet-stream',
    size_bytes INTEGER NOT NULL,
    created_at INTEGER NOT NULL,
    FOREIGN KEY(conversation_id) REFERENCES conversations(id)
);

CREATE INDEX IF NOT EXISTS idx_msg_conv_time ON messages(conversation_id, created_at);
CREATE INDEX IF NOT EXISTS idx_conv_remote ON conversations(remote_system, remote_ticket_id);
"""


def now_ms() -> int:
    return int(time.time() * 1000)


# ==========================================================================
# 配置
# ==========================================================================


@dataclasses.dataclass
class Config:
    shared_secret: str
    data_dir: Path
    listen_host: str = "127.0.0.1"
    listen_port: int = DEFAULT_PORT
    admin_user: str = "admin"
    admin_password: str = ""
    webhook_token: str = ""
    max_body_bytes: int = DEFAULT_MAX_BODY_BYTES

    @classmethod
    def from_env(cls, env: Optional[Dict[str, str]] = None) -> "Config":
        env = os.environ if env is None else env
        secret = env.get("FEEDBACK_SHARED_SECRET", "").strip()
        if not secret:
            raise SystemExit(
                "FEEDBACK_SHARED_SECRET 未设置；桌面端与管理端必须填同一个值"
            )
        return cls(
            shared_secret=secret,
            data_dir=Path(env.get("FEEDBACK_DATA_DIR", "./feedback-data")).expanduser(),
            listen_host=env.get("FEEDBACK_LISTEN_HOST", "127.0.0.1"),
            listen_port=int(env.get("FEEDBACK_LISTEN_PORT", str(DEFAULT_PORT))),
            admin_user=env.get("FEEDBACK_ADMIN_USER", "admin"),
            admin_password=env.get("FEEDBACK_ADMIN_PASSWORD", ""),
            webhook_token=env.get("FEEDBACK_WEBHOOK_TOKEN", ""),
            max_body_bytes=int(
                env.get("FEEDBACK_MAX_BODY_BYTES", str(DEFAULT_MAX_BODY_BYTES))
            ),
        )


# ==========================================================================
# 存储
# ==========================================================================


class Store:
    """SQLite 中继镜像。每次操作开一条短连接，避免跨线程共享连接。"""

    def __init__(self, db_path: Path, attachments_dir: Path) -> None:
        self.db_path = db_path
        self.attachments_dir = attachments_dir
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.attachments_dir.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    @contextlib.contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """每次操作一条短连接：提交即关闭，避免长跑服务泄漏文件描述符。"""
        conn = sqlite3.connect(str(self.db_path), timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # ---- conversations ---------------------------------------------------

    def upsert_conversation(
        self,
        conversation_id: str,
        title: str,
        app_version: str,
        os_info: str,
        created_at: int,
        client_id: str,
    ) -> bool:
        """Insert the conversation if unseen. Returns True when it was created."""
        ts = now_ms()
        with self._connect() as conn:
            cur = conn.execute(
                """INSERT OR IGNORE INTO conversations
                   (id, client_id, title, status, app_version, os_info,
                    created_at, updated_at)
                   VALUES (?, ?, ?, 'open', ?, ?, ?, ?)""",
                (conversation_id, client_id, title, app_version, os_info, created_at, ts),
            )
            return cur.rowcount > 0

    def get_conversation(self, conversation_id: str) -> Optional[sqlite3.Row]:
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT * FROM conversations WHERE id = ?", (conversation_id,)
            )
            return cur.fetchone()

    def list_conversations(self, limit: int = 200) -> List[sqlite3.Row]:
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT * FROM conversations ORDER BY updated_at DESC LIMIT ?", (limit,)
            )
            return list(cur.fetchall())

    def set_remote_ticket(
        self, conversation_id: str, system: str, ticket_id: str, ticket_url: str
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE conversations SET remote_system = ?, remote_ticket_id = ?, "
                "remote_ticket_url = ?, updated_at = ? WHERE id = ?",
                (system, ticket_id, ticket_url, now_ms(), conversation_id),
            )

    def find_by_remote_ticket(
        self, system: str, ticket_id: str
    ) -> Optional[sqlite3.Row]:
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT * FROM conversations WHERE remote_system = ? AND remote_ticket_id = ?",
                (system, ticket_id),
            )
            return cur.fetchone()

    # ---- messages --------------------------------------------------------

    def add_message(
        self,
        message_id: str,
        conversation_id: str,
        role: str,
        body: str,
        media_ids: List[str],
        created_at: int,
        origin: str,
    ) -> bool:
        """Insert a message. Returns False when the id was already known.

        幂等很重要：桌面端在没收到 2xx 之前会重发同一条消息。
        """
        with self._connect() as conn:
            cur = conn.execute(
                """INSERT OR IGNORE INTO messages
                   (id, conversation_id, role, body, media_ids, origin, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    message_id,
                    conversation_id,
                    role,
                    body,
                    json.dumps(media_ids),
                    origin,
                    created_at,
                ),
            )
            if cur.rowcount > 0:
                conn.execute(
                    "UPDATE conversations SET updated_at = ? WHERE id = ?",
                    (now_ms(), conversation_id),
                )
            return cur.rowcount > 0

    def list_messages(
        self,
        conversation_id: str,
        since: int = 0,
        roles: Optional[Tuple[str, ...]] = None,
        limit: int = 500,
    ) -> List[sqlite3.Row]:
        sql = "SELECT * FROM messages WHERE conversation_id = ? AND created_at > ?"
        params: List[Any] = [conversation_id, since]
        if roles:
            placeholders = ", ".join("?" for _ in roles)
            sql += " AND role IN ({})".format(placeholders)
            params.extend(roles)
        sql += " ORDER BY created_at ASC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            cur = conn.execute(sql, params)
            return list(cur.fetchall())

    # ---- attachments -----------------------------------------------------

    def save_attachment(
        self, media_id: str, conversation_id: str, data: bytes, mime_type: str
    ) -> None:
        if not MEDIA_ID_RE.match(media_id):
            raise ValueError("invalid media id")
        path = self.attachments_dir / media_id
        path.write_bytes(data)
        with self._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO attachments
                   (id, conversation_id, mime_type, size_bytes, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (media_id, conversation_id, mime_type, len(data), now_ms()),
            )

    def get_attachment(self, media_id: str) -> Optional[sqlite3.Row]:
        with self._connect() as conn:
            cur = conn.execute("SELECT * FROM attachments WHERE id = ?", (media_id,))
            return cur.fetchone()

    def attachment_path(self, media_id: str) -> Path:
        return self.attachments_dir / media_id


# ==========================================================================
# 转发器
# ==========================================================================


def _http_json(
    method: str, url: str, payload: Optional[Dict[str, Any]], headers: Dict[str, str]
) -> Dict[str, Any]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    for key, value in headers.items():
        req.add_header(key, value)
    req.add_header("Accept", "application/json")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as resp:
        raw = resp.read()
    return json.loads(raw.decode("utf-8")) if raw else {}


def _summary(title: str) -> str:
    return title if len(title) <= 100 else title[:97] + "..."


class Forwarder:
    """把新会话/新消息推给外部系统。默认实现什么也不做。"""

    name = "none"

    def is_enabled(self) -> bool:
        return False

    def create_ticket(self, conv: sqlite3.Row, body: str) -> Tuple[str, str]:
        """建工单，返回 (ticket_id, ticket_url)；不做事的实现返回空串。"""
        return "", ""

    def add_comment(self, conv: sqlite3.Row, body: str) -> None:
        return


class JiraForwarder(Forwarder):
    name = "jira"

    def __init__(
        self, base_url: str, email: str, token: str, project: str, issue_type: str = "Task"
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.email = email
        self.token = token
        self.project = project
        self.issue_type = issue_type

    def is_enabled(self) -> bool:
        return bool(self.base_url and self.token and self.project)

    def _headers(self) -> Dict[str, str]:
        raw = "{}:{}".format(self.email, self.token).encode("utf-8")
        return {"Authorization": "Basic " + base64.b64encode(raw).decode("ascii")}

    def create_ticket(self, conv: sqlite3.Row, body: str) -> Tuple[str, str]:
        payload = {
            "fields": {
                "project": {"key": self.project},
                "summary": _summary(conv["title"]),
                "description": body,
                "issuetype": {"name": self.issue_type},
            }
        }
        data = _http_json(
            "POST", self.base_url + "/rest/api/2/issue", payload, self._headers()
        )
        key = str(data.get("key", ""))
        return key, "{}/browse/{}".format(self.base_url, key) if key else ""

    def add_comment(self, conv: sqlite3.Row, body: str) -> None:
        key = conv["remote_ticket_id"]
        if not key:
            return
        _http_json(
            "POST",
            "{}/rest/api/2/issue/{}/comment".format(self.base_url, key),
            {"body": body},
            self._headers(),
        )


class GitLabForwarder(Forwarder):
    name = "gitlab"

    def __init__(self, base_url: str, token: str, project: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.project = project

    def is_enabled(self) -> bool:
        return bool(self.base_url and self.token and self.project)

    def _headers(self) -> Dict[str, str]:
        return {"PRIVATE-TOKEN": self.token}

    def _project_url(self) -> str:
        return "{}/api/v4/projects/{}".format(
            self.base_url, urllib.parse.quote(self.project, safe="")
        )

    def create_ticket(self, conv: sqlite3.Row, body: str) -> Tuple[str, str]:
        data = _http_json(
            "POST",
            self._project_url() + "/issues",
            {"title": _summary(conv["title"]), "description": body},
            self._headers(),
        )
        iid = str(data.get("iid", ""))
        return iid, str(data.get("web_url", ""))

    def add_comment(self, conv: sqlite3.Row, body: str) -> None:
        iid = conv["remote_ticket_id"]
        if not iid:
            return
        _http_json(
            "POST",
            "{}/issues/{}/notes".format(self._project_url(), iid),
            {"body": body},
            self._headers(),
        )


class SmtpForwarder(Forwarder):
    """邮件转发。单向通知：回复请走管理页或 Jira/GitLab webhook。"""

    name = "smtp"

    def __init__(
        self,
        host: str,
        port: int,
        sender: str,
        recipient: str,
        username: str = "",
        password: str = "",
        use_tls: bool = False,
        store: Optional[Store] = None,
    ) -> None:
        self.host = host
        self.port = port
        self.sender = sender
        self.recipient = recipient
        self.username = username
        self.password = password
        self.use_tls = use_tls
        self.store = store

    def is_enabled(self) -> bool:
        return bool(self.host and self.sender and self.recipient)

    def create_ticket(self, conv: sqlite3.Row, body: str) -> Tuple[str, str]:
        self._send(conv, body, [])
        return "", ""

    def add_comment(self, conv: sqlite3.Row, body: str) -> None:
        self._send(conv, body, [])

    def _thread_id(self, conv: sqlite3.Row) -> str:
        return "<sage-feedback-{}@sage.local>".format(conv["id"])

    def _send(self, conv: sqlite3.Row, body: str, media_ids: List[str]) -> None:
        msg = EmailMessage()
        msg["Subject"] = "[Sage反馈] {}".format(conv["title"])
        msg["From"] = self.sender
        msg["To"] = self.recipient
        msg["Message-ID"] = "<sage-feedback-{}-{}@sage.local>".format(
            conv["id"], uuid.uuid4().hex[:8]
        )
        msg["In-Reply-To"] = self._thread_id(conv)
        msg["References"] = self._thread_id(conv)
        msg.set_content(
            "会话: {}\n版本: {}\n系统: {}\n\n{}".format(
                conv["id"], conv["app_version"], conv["os_info"], body
            )
        )

        if self.store is not None:
            for media_id in media_ids:
                row = self.store.get_attachment(media_id)
                path = self.store.attachment_path(media_id)
                if row is None or not path.exists():
                    continue
                maintype, _, subtype = row["mime_type"].partition("/")
                msg.add_attachment(
                    path.read_bytes(),
                    maintype=maintype or "application",
                    subtype=subtype or "octet-stream",
                    filename=media_id,
                )

        if self.use_tls:
            client: Any = smtplib.SMTP_SSL(self.host, self.port, timeout=HTTP_TIMEOUT_S)
        else:
            client = smtplib.SMTP(self.host, self.port, timeout=HTTP_TIMEOUT_S)
        try:
            if self.username:
                client.login(self.username, self.password)
            client.send_message(msg)
        finally:
            client.quit()


def build_forwarder(
    env: Optional[Dict[str, str]] = None, store: Optional[Store] = None
) -> Forwarder:
    """按 Jira → GitLab → SMTP 的优先级挑第一个配置完整的后端。"""
    env = os.environ if env is None else env

    jira = JiraForwarder(
        base_url=env.get("FEEDBACK_JIRA_URL", ""),
        email=env.get("FEEDBACK_JIRA_EMAIL", ""),
        token=env.get("FEEDBACK_JIRA_TOKEN", ""),
        project=env.get("FEEDBACK_JIRA_PROJECT", ""),
        issue_type=env.get("FEEDBACK_JIRA_ISSUE_TYPE", "Task"),
    )
    if jira.is_enabled():
        return jira

    gitlab = GitLabForwarder(
        base_url=env.get("FEEDBACK_GITLAB_URL", ""),
        token=env.get("FEEDBACK_GITLAB_TOKEN", ""),
        project=env.get("FEEDBACK_GITLAB_PROJECT", ""),
    )
    if gitlab.is_enabled():
        return gitlab

    smtp = SmtpForwarder(
        host=env.get("FEEDBACK_SMTP_HOST", ""),
        port=int(env.get("FEEDBACK_SMTP_PORT", "25")),
        sender=env.get("FEEDBACK_SMTP_FROM", ""),
        recipient=env.get("FEEDBACK_SMTP_TO", ""),
        username=env.get("FEEDBACK_SMTP_USER", ""),
        password=env.get("FEEDBACK_SMTP_PASSWORD", ""),
        use_tls=env.get("FEEDBACK_SMTP_TLS", "0") == "1",
        store=store,
    )
    if smtp.is_enabled():
        return smtp

    return Forwarder()


# ==========================================================================
# 中继编排（不依赖 HTTP，方便单测）
# ==========================================================================


class Relay:
    def __init__(self, store: Store, forwarder: Optional[Forwarder] = None) -> None:
        self.store = store
        self.forwarder = forwarder or Forwarder()

    def ingest_user_message(
        self, conversation_id: str, payload: Dict[str, Any], client_id: str
    ) -> Dict[str, Any]:
        """落库一条桌面端消息；首次见到该会话时建工单（异步）。"""
        title = str(payload.get("title") or "").strip() or "未命名反馈"
        app_version = str(payload.get("app_version") or "")
        os_info = str(payload.get("os_info") or "")
        created_at = _as_int(payload.get("conversation_created_at")) or now_ms()

        is_new = self.store.upsert_conversation(
            conversation_id, title, app_version, os_info, created_at, client_id
        )
        inserted = self.store.add_message(
            message_id=str(payload["id"]),
            conversation_id=conversation_id,
            role=str(payload.get("role") or "user"),
            body=str(payload.get("body") or ""),
            media_ids=[str(m) for m in payload.get("media_ids") or []],
            created_at=_as_int(payload.get("created_at")) or now_ms(),
            origin="client",
        )

        conv = self.store.get_conversation(conversation_id)
        if conv is not None and inserted:
            body = self._transcript(conversation_id)
            if is_new or not conv["remote_ticket_id"]:
                self._spawn(self._create_ticket, conversation_id, body)
            else:
                self._spawn(self._add_comment, conversation_id, body)

        return {"received": True, "duplicate": not inserted}

    def add_admin_message(
        self, conversation_id: str, body: str, origin: str
    ) -> Optional[str]:
        body = body.strip()
        if not body:
            return None
        message_id = str(uuid.uuid4())
        self.store.add_message(
            message_id=message_id,
            conversation_id=conversation_id,
            role="admin",
            body=body,
            media_ids=[],
            created_at=now_ms(),
            origin=origin,
        )
        return message_id

    def replies_since(self, conversation_id: str, since: int) -> List[Dict[str, Any]]:
        rows = self.store.list_messages(conversation_id, since=since, roles=("admin",))
        return [
            {
                "id": row["id"],
                "role": "admin",
                "body": row["body"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    # ---- webhooks --------------------------------------------------------

    def handle_jira_webhook(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        event = payload.get("webhookEvent") or payload.get("webhookEventName") or ""
        if event != "comment_created":
            return {"stored": False, "reason": "ignored event: {}".format(event or "?")}
        issue = payload.get("issue") or {}
        comment = payload.get("comment") or {}
        key = str(issue.get("key") or "")
        body = str(comment.get("body") or "").strip()
        return self._store_webhook_reply("jira", key, body, comment.get("created"))

    def handle_gitlab_webhook(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        if payload.get("object_kind") != "note":
            return {
                "stored": False,
                "reason": "ignored event: {}".format(payload.get("object_kind") or "?"),
            }
        issue = payload.get("issue") or {}
        attrs = payload.get("object_attributes") or {}
        iid = str(issue.get("iid") or attrs.get("noteable_iid") or "")
        body = str(attrs.get("note") or "").strip()
        return self._store_webhook_reply("gitlab", iid, body, attrs.get("created_at"))

    def _store_webhook_reply(
        self, system: str, ticket_id: str, body: str, created_at: Any
    ) -> Dict[str, Any]:
        if not ticket_id or not body:
            return {"stored": False, "reason": "missing ticket id or empty body"}
        conv = self.store.find_by_remote_ticket(system, ticket_id)
        if conv is None:
            LOG.warning("webhook for unknown ticket %s/%s", system, ticket_id)
            return {"stored": False, "reason": "unknown ticket"}
        message_id = self.add_admin_message(conv["id"], body, origin=system)
        if message_id is None:
            return {"stored": False, "reason": "empty body"}
        return {"stored": True, "conversation_id": conv["id"]}

    # ---- forwarding ------------------------------------------------------

    def _transcript(self, conversation_id: str) -> str:
        rows = self.store.list_messages(conversation_id, roles=("user",))
        return "\n\n".join("[{}] {}".format(r["created_at"], r["body"]) for r in rows)

    def _create_ticket(self, conversation_id: str, body: str) -> None:
        conv = self.store.get_conversation(conversation_id)
        if conv is None:
            return
        try:
            ticket_id, ticket_url = self.forwarder.create_ticket(conv, body)
        except Exception as exc:  # noqa: BLE001 - 转发失败不能影响中继
            LOG.warning("create_ticket failed for %s: %s", conversation_id, exc)
            return
        if ticket_id:
            self.store.set_remote_ticket(
                conversation_id, self.forwarder.name, ticket_id, ticket_url
            )
            LOG.info(
                "conversation %s -> %s %s", conversation_id, self.forwarder.name, ticket_id
            )

    def _add_comment(self, conversation_id: str, body: str) -> None:
        conv = self.store.get_conversation(conversation_id)
        if conv is None:
            return
        try:
            self.forwarder.add_comment(conv, body)
        except Exception as exc:  # noqa: BLE001
            LOG.warning("add_comment failed for %s: %s", conversation_id, exc)

    @staticmethod
    def _spawn(fn: Any, *args: Any) -> None:
        threading.Thread(target=fn, args=args, daemon=True).start()


def _as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


# ==========================================================================
# HTTP 层
# ==========================================================================


class FeedbackHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "SageFeedbackRelay/1.0"

    # 由 build_server() 注入到派生子类上
    config: Config
    relay: Relay

    # ---- 基础工具 --------------------------------------------------------

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003 - 覆盖基类
        LOG.info("%s %s", self.address_string(), fmt % args)

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        # 每条响应后关闭连接：鉴权失败等早退路径可能没读完请求体，
        # 若保持 keep-alive 会让后续请求错位。
        self.close_connection = True
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _send_json(self, status: int, payload: Any) -> None:
        self._send(
            status,
            json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            "application/json; charset=utf-8",
        )

    def _send_html(self, status: int, markup: str) -> None:
        self._send(status, markup.encode("utf-8"), "text/html; charset=utf-8")

    def _read_body(self) -> bytes:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0:
            return b""
        if length > self.config.max_body_bytes:
            raise ValueError("body too large")
        return self.rfile.read(length)

    def _read_json(self) -> Dict[str, Any]:
        raw = self._read_body()
        if not raw:
            return {}
        parsed = json.loads(raw.decode("utf-8"))
        if not isinstance(parsed, dict):
            raise ValueError("expected a JSON object")
        return parsed

    # ---- 鉴权 ------------------------------------------------------------

    def _check_bearer(self) -> bool:
        header = self.headers.get("Authorization") or ""
        if not header.startswith("Bearer "):
            self._send_json(401, {"detail": "missing bearer token"})
            return False
        if not _secure_eq(header[len("Bearer ") :], self.config.shared_secret):
            self._send_json(401, {"detail": "invalid shared secret"})
            return False
        return True

    def _check_webhook(self, query: Dict[str, List[str]]) -> bool:
        expected = self.config.webhook_token
        if not expected:
            self._send_json(404, {"detail": "webhooks disabled"})
            return False
        provided = self.headers.get("X-Feedback-Token") or query.get("token", [""])[0]
        if not _secure_eq(provided, expected):
            self._send_json(401, {"detail": "invalid webhook token"})
            return False
        return True

    def _check_admin(self) -> bool:
        if not self.config.admin_password:
            self._send_html(404, "<h1>管理页未启用</h1>")
            return False
        header = self.headers.get("Authorization") or ""
        if not header.startswith("Basic "):
            self._challenge_admin()
            return False
        try:
            decoded = base64.b64decode(header[len("Basic ") :]).decode("utf-8")
        except Exception:  # noqa: BLE001
            self._challenge_admin()
            return False
        user, _, password = decoded.partition(":")
        if _secure_eq(user, self.config.admin_user) and _secure_eq(
            password, self.config.admin_password
        ):
            return True
        self._challenge_admin()
        return False

    def _challenge_admin(self) -> None:
        self.close_connection = True
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="Sage Feedback"')
        self.send_header("Content-Length", "0")
        self.send_header("Connection", "close")
        self.end_headers()

    # ---- 路由 ------------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler 协议
        parsed = urllib.parse.urlsplit(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        if path == "/api/v1/feedback/health":
            self._send_json(
                200,
                {"status": "ok", "conversations": len(self.relay.store.list_conversations())},
            )
            return

        match = re.match(r"^/api/v1/feedback/conversations/([^/]+)/messages$", path)
        if match:
            if not self._check_bearer():
                return
            self._handle_list_messages(match.group(1), query)
            return

        match = re.match(r"^/api/v1/feedback/attachments/([^/]+)$", path)
        if match:
            if not self._check_bearer():
                return
            self._handle_get_attachment(match.group(1))
            return

        if path == "/":
            if not self._check_admin():
                return
            self._send_html(200, self._render_list())
            return

        match = re.match(r"^/conversation/([^/]+)$", path)
        if match:
            if not self._check_admin():
                return
            self._send_html(200, self._render_detail(match.group(1)))
            return

        self._send_json(404, {"detail": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlsplit(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        match = re.match(r"^/api/v1/feedback/conversations/([^/]+)/messages$", path)
        if match:
            if not self._check_bearer():
                return
            self._handle_ingest(match.group(1))
            return

        match = re.match(
            r"^/api/v1/feedback/conversations/([^/]+)/attachments/([^/]+)$", path
        )
        if match:
            if not self._check_bearer():
                return
            self._handle_upload_attachment(match.group(1), match.group(2))
            return

        if path == "/api/v1/webhooks/jira":
            if not self._check_webhook(query):
                return
            self._handle_webhook(self.relay.handle_jira_webhook)
            return

        if path == "/api/v1/webhooks/gitlab":
            if not self._check_webhook(query):
                return
            self._handle_webhook(self.relay.handle_gitlab_webhook)
            return

        match = re.match(r"^/conversation/([^/]+)/reply$", path)
        if match:
            if not self._check_admin():
                return
            self._handle_admin_reply(match.group(1))
            return

        self._send_json(404, {"detail": "not found"})

    # ---- API 处理 --------------------------------------------------------

    def _handle_ingest(self, conversation_id: str) -> None:
        if not CONVERSATION_ID_RE.match(conversation_id):
            self._send_json(400, {"detail": "invalid conversation id"})
            return
        try:
            payload = self._read_json()
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            self._send_json(400, {"detail": str(exc)})
            return
        if not payload.get("id") or not payload.get("body"):
            self._send_json(400, {"detail": "id and body are required"})
            return

        client_id = self.headers.get("X-Client-Id") or ""
        result = self.relay.ingest_user_message(conversation_id, payload, client_id)
        self._send_json(200, result)

    def _handle_list_messages(
        self, conversation_id: str, query: Dict[str, List[str]]
    ) -> None:
        since = _as_int((query.get("since") or ["0"])[0])
        self._send_json(200, self.relay.replies_since(conversation_id, since))

    def _handle_upload_attachment(self, conversation_id: str, media_id: str) -> None:
        if not MEDIA_ID_RE.match(media_id):
            self._send_json(400, {"detail": "invalid media id"})
            return
        try:
            data = self._read_body()
        except ValueError as exc:
            self._send_json(413, {"detail": str(exc)})
            return
        if not data:
            self._send_json(400, {"detail": "empty body"})
            return
        mime = self.headers.get("Content-Type") or "application/octet-stream"
        try:
            self.relay.store.save_attachment(media_id, conversation_id, data, mime)
        except ValueError as exc:
            self._send_json(400, {"detail": str(exc)})
            return
        self._send_json(200, {"id": media_id, "received": True})

    def _handle_get_attachment(self, media_id: str) -> None:
        if not MEDIA_ID_RE.match(media_id):
            self._send_json(400, {"detail": "invalid media id"})
            return
        row = self.relay.store.get_attachment(media_id)
        path = self.relay.store.attachment_path(media_id)
        if row is None or not path.exists():
            self._send_json(404, {"detail": "not found"})
            return
        self._send(200, path.read_bytes(), row["mime_type"])

    def _handle_webhook(self, handler: Any) -> None:
        try:
            payload = self._read_json()
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            self._send_json(400, {"detail": str(exc)})
            return
        self._send_json(200, handler(payload))

    def _handle_admin_reply(self, conversation_id: str) -> None:
        raw = self._read_body().decode("utf-8", errors="replace")
        fields = urllib.parse.parse_qs(raw)
        body = (fields.get("body") or [""])[0]
        if self.relay.store.get_conversation(conversation_id) is None:
            self._send_html(404, "<h1>会话不存在</h1>")
            return
        self.relay.add_admin_message(conversation_id, body, origin="admin-page")
        self.send_response(303)
        self.send_header("Location", "/conversation/{}".format(conversation_id))
        self.send_header("Content-Length", "0")
        self.end_headers()

    # ---- 管理页渲染 ------------------------------------------------------

    def _render_list(self) -> str:
        rows = self.relay.store.list_conversations()
        items = []
        for row in rows:
            items.append(
                '<tr><td><a href="/conversation/{cid}">{title}</a></td>'
                "<td>{status}</td><td>{ticket}</td><td>{updated}</td></tr>".format(
                    cid=html.escape(row["id"]),
                    title=html.escape(row["title"]),
                    status=html.escape(row["status"]),
                    ticket=html.escape(
                        "{} {}".format(
                            row["remote_system"] or "", row["remote_ticket_id"] or ""
                        ).strip()
                        or "-"
                    ),
                    updated=_fmt_time(row["updated_at"]),
                )
            )
        if not items:
            items.append('<tr><td colspan="4">还没有收到反馈</td></tr>')
        return _page(
            "反馈列表",
            "<h1>反馈列表</h1>"
            '<table><thead><tr><th>标题</th><th>状态</th><th>工单</th>'
            "<th>最后更新</th></tr></thead><tbody>{}</tbody></table>".format(
                "".join(items)
            ),
        )

    def _render_detail(self, conversation_id: str) -> str:
        conv = self.relay.store.get_conversation(conversation_id)
        if conv is None:
            return _page("未找到", "<h1>会话不存在</h1>")
        blocks = []
        for row in self.relay.store.list_messages(conversation_id):
            media = ""
            for media_id in json.loads(row["media_ids"] or "[]"):
                media += (
                    '<div><a href="/api/v1/feedback/attachments/{0}">{0}</a></div>'
                ).format(html.escape(str(media_id)))
            blocks.append(
                '<div class="msg {role}"><div class="meta">{role} · {when} · {origin}</div>'
                "<pre>{body}</pre>{media}</div>".format(
                    role=html.escape(row["role"]),
                    when=_fmt_time(row["created_at"]),
                    origin=html.escape(row["origin"]),
                    body=html.escape(row["body"]),
                    media=media,
                )
            )
        header = (
            "<h1>{title}</h1>"
            '<p class="meta">会话 {cid} · 版本 {ver} · 系统 {os} · 状态 {status}'
            " · 工单 {ticket}</p>".format(
                title=html.escape(conv["title"]),
                cid=html.escape(conv["id"]),
                ver=html.escape(conv["app_version"] or "-"),
                os=html.escape(conv["os_info"] or "-"),
                status=html.escape(conv["status"]),
                ticket=html.escape(conv["remote_ticket_url"] or "-"),
            )
        )
        form = (
            '<form method="post" action="/conversation/{cid}/reply">'
            '<textarea name="body" rows="4" placeholder="回复用户…"></textarea>'
            '<button type="submit">发送回复</button></form>'
        ).format(cid=html.escape(conv["id"]))
        return _page(
            conv["title"],
            header + "".join(blocks) + form + '<p><a href="/">← 返回列表</a></p>',
        )


def _page(title: str, body: str) -> str:
    return (
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        "<title>{title}</title><style>"
        "body{{font-family:system-ui,sans-serif;margin:2rem;max-width:60rem}}"
        "table{{border-collapse:collapse;width:100%}}"
        "td,th{{border-bottom:1px solid #ddd;padding:.4rem;text-align:left}}"
        ".msg{{border-left:3px solid #ccc;padding:.5rem 1rem;margin:.5rem 0}}"
        ".msg.admin{{border-color:#2b6cb0}}"
        ".msg.user{{border-color:#888}}"
        ".meta{{color:#666;font-size:.85rem}}"
        "pre{{white-space:pre-wrap;margin:.4rem 0}}"
        "textarea{{width:100%;font-family:inherit}}"
        "</style></head><body>{body}</body></html>"
    ).format(title=html.escape(title), body=body)


def _fmt_time(ms: Any) -> str:
    try:
        return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).strftime(
            "%Y-%m-%d %H:%M UTC"
        )
    except (TypeError, ValueError, OSError):
        return "-"


def _secure_eq(left: str, right: str) -> bool:
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


# ==========================================================================
# 入口
# ==========================================================================


def build_server(
    config: Config, forwarder: Optional[Forwarder] = None
) -> ThreadingHTTPServer:
    store = Store(config.data_dir / "feedback.db", config.data_dir / "attachments")
    if forwarder is None:
        forwarder = build_forwarder(store=store)
    relay = Relay(store, forwarder)

    handler = type(
        "BoundFeedbackHandler",
        (FeedbackHandler,),
        {"config": config, "relay": relay},
    )

    server = ThreadingHTTPServer((config.listen_host, config.listen_port), handler)
    server.daemon_threads = True
    return server


def main(argv: Optional[List[str]] = None) -> int:
    del argv  # 目前没有命令行参数：全部走环境变量，便于 systemd / 计划任务托管
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    config = Config.from_env()
    server = build_server(config)
    relay = server.RequestHandlerClass.relay  # type: ignore[attr-defined]

    LOG.info(
        "listening on http://%s:%d (data=%s, forwarder=%s, admin=%s, webhooks=%s)",
        config.listen_host,
        config.listen_port,
        config.data_dir,
        relay.forwarder.name,
        "on" if config.admin_password else "off",
        "on" if config.webhook_token else "off",
    )
    if relay.forwarder.name == "none":
        LOG.warning("未配置任何转发后端：反馈只会留在本机，请用管理页处理")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        LOG.info("shutting down")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
