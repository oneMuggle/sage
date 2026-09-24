# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容
"""browser_events 下载跟踪单测（Round 5 B4 / SN3）。

DownloadTracker 纯状态机直接测；事件通道用本地迷你 WS 服务端对拍
（复用 test_browser_tool 的帧编码思路，只覆盖 setDownloadBehavior 应答 + 事件分发）。
"""

import base64
import hashlib
import json
import socket
import struct
import threading
import time
from typing import List

import pytest

from backend.tools import browser_events
from backend.tools.browser_events import DownloadTracker, list_download_dir

pytestmark = [pytest.mark.unit]


# ---------------------------------------------------------------------------
# DownloadTracker
# ---------------------------------------------------------------------------


def test_tracker_records_begin_progress_complete(tmp_path):
    tracker = DownloadTracker(str(tmp_path))
    tracker.handle_event(
        "Browser.downloadWillBegin",
        {"guid": "g1", "url": "https://s/x.pdf", "suggestedFilename": "x.pdf", "frameId": "f"},
    )
    assert tracker.pending()[0]["suggested_filename"] == "x.pdf"
    tracker.handle_event(
        "Browser.downloadProgress",
        {"guid": "g1", "state": "inProgress", "receivedBytes": 10, "totalBytes": 100},
    )
    assert tracker.snapshot()[0]["received_bytes"] == 10
    assert tracker.snapshot()[0]["total_bytes"] == 100
    (tmp_path / "g1").write_bytes(b"%PDF" * 25)
    tracker.handle_event(
        "Browser.downloadProgress",
        {"guid": "g1", "state": "completed", "receivedBytes": 100, "totalBytes": 100},
    )
    record = tracker.snapshot()[0]
    assert record["state"] == "completed"
    assert record["path"] == str(tmp_path / "g1")
    assert tracker.pending() == []
    assert tracker.wait_for_complete(0.0) is True


def test_tracker_resolves_suggested_filename_fallback(tmp_path):
    tracker = DownloadTracker(str(tmp_path))
    tracker.handle_event(
        "Browser.downloadWillBegin", {"guid": "g2", "url": "u", "suggestedFilename": "paper.pdf"}
    )
    tracker.handle_event("Browser.downloadProgress", {"guid": "g2", "state": "completed"})
    assert tracker.snapshot()[0]["path"] is None  # 文件还没出现
    (tmp_path / "paper.pdf").write_bytes(b"x")
    assert tracker.resolve_completed_path("g2") == str(tmp_path / "paper.pdf")
    assert tracker.mark_artifact_recorded("g2") is True
    assert tracker.mark_artifact_recorded("g2") is False


def test_tracker_wait_times_out_and_wakes_on_event(tmp_path):
    tracker = DownloadTracker(str(tmp_path))
    tracker.handle_event("Browser.downloadWillBegin", {"guid": "g3", "url": "u"})
    assert tracker.wait_for_complete(0.3) is False

    def _finish():
        time.sleep(0.2)
        tracker.handle_event("Browser.downloadProgress", {"guid": "g3", "state": "canceled"})

    threading.Thread(target=_finish, daemon=True).start()
    assert tracker.wait_for_complete(5.0) is True
    assert tracker.snapshot()[0]["state"] == "canceled"


def test_tracker_caps_records(tmp_path, monkeypatch):
    monkeypatch.setattr(browser_events, "MAX_DOWNLOAD_RECORDS", 3)
    tracker = DownloadTracker(str(tmp_path))
    for i in range(5):
        tracker.handle_event("Browser.downloadWillBegin", {"guid": f"g{i}", "url": "u"})
        tracker.handle_event("Browser.downloadProgress", {"guid": f"g{i}", "state": "completed"})
    assert [r["guid"] for r in tracker.snapshot()] == ["g2", "g3", "g4"]


def test_list_download_dir_marks_crdownload(tmp_path):
    (tmp_path / "a.pdf").write_bytes(b"1")
    (tmp_path / "b.zip.crdownload").write_bytes(b"12")
    items = {i["name"]: i for i in list_download_dir(str(tmp_path))}
    assert items["a.pdf"]["state"] == "completed"
    assert items["b.zip.crdownload"]["state"] == "inProgress"
    assert list_download_dir(str(tmp_path / "missing")) == []


# ---------------------------------------------------------------------------
# 事件通道：迷你 WS 服务端
# ---------------------------------------------------------------------------

_WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def _ws_send_server_text(conn, text):
    payload = text.encode("utf-8")
    length = len(payload)
    if length < 126:
        header = struct.pack("!BB", 0x81, length)
    elif length < 65536:
        header = struct.pack("!BBH", 0x81, 126, length)
    else:
        header = struct.pack("!BBQ", 0x81, 127, length)
    conn.sendall(header + payload)


def _ws_recv_client_text(conn):
    first, second = conn.recv(2)
    length = second & 0x7F
    if length == 126:
        (length,) = struct.unpack("!H", conn.recv(2))
    elif length == 127:
        (length,) = struct.unpack("!Q", conn.recv(8))
    mask = conn.recv(4)
    data = b""
    while len(data) < length:
        data += conn.recv(length - len(data))
    return bytes(b ^ mask[i % 4] for i, b in enumerate(data)).decode("utf-8")


def _serve_once(server, events, respond_error=False, hold=None):
    conn, _ = server.accept()
    conn.settimeout(5)
    request = b""
    while b"\r\n\r\n" not in request:
        request += conn.recv(4096)
    key = next(
        line.split(":", 1)[1].strip()
        for line in request.decode("latin-1").split("\r\n")
        if line.lower().startswith("sec-websocket-key")
    )
    accept = base64.b64encode(hashlib.sha1((key + _WS_GUID).encode()).digest()).decode()
    conn.sendall(
        (
            "HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
            f"Connection: Upgrade\r\nSec-WebSocket-Accept: {accept}\r\n\r\n"
        ).encode()
    )
    message = json.loads(_ws_recv_client_text(conn))
    assert message["method"] == "Browser.setDownloadBehavior"
    assert message["params"]["eventsEnabled"] is True
    if respond_error:
        _ws_send_server_text(conn, json.dumps({"id": message["id"], "error": {"message": "nope"}}))
        conn.close()
        return
    _ws_send_server_text(conn, json.dumps({"id": message["id"], "result": {}}))
    for event in events:
        _ws_send_server_text(conn, json.dumps(event))
        time.sleep(0.02)
    if hold is not None:
        hold.wait(5)
    conn.close()


@pytest.fixture()
def ws_server():
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    server.settimeout(5)
    yield server
    server.close()
    browser_events.stop_all_tracking()


def test_event_channel_receives_download_events(ws_server, tmp_path):
    port = ws_server.getsockname()[1]
    hold = threading.Event()
    events = [
        {"method": "Target.targetInfoChanged", "params": {}},  # 无关事件被忽略
        {
            "method": "Browser.downloadWillBegin",
            "params": {"guid": "g", "url": "https://s/x.pdf", "suggestedFilename": "x.pdf"},
        },
        {
            "method": "Browser.downloadProgress",
            "params": {"guid": "g", "state": "completed", "receivedBytes": 4},
        },
    ]
    thread = threading.Thread(
        target=_serve_once, args=(ws_server, events), kwargs={"hold": hold}, daemon=True
    )
    thread.start()
    (tmp_path / "g").write_bytes(b"%PDF")

    tracker = browser_events.start_download_tracking(
        "b-evt", port, "/devtools/browser/x", str(tmp_path)
    )
    assert tracker.connected is True
    assert tracker.wait_for_complete(5.0) is True
    # 等待记录到达且进入 completed（begin → progress completed 两步，存在先后）
    record = None
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        snaps = tracker.snapshot()
        if snaps and snaps[0].get("state") == "completed":
            record = snaps[0]
            break
        time.sleep(0.05)
    assert record is not None, "下载记录未在时限内到达 completed 状态"
    assert record["url"] == "https://s/x.pdf"
    assert record["state"] == "completed"
    assert record["path"] == str(tmp_path / "g")
    assert browser_events.get_download_tracker("b-evt") is tracker
    # 幂等：已连接的通道复用
    assert browser_events.start_download_tracking("b-evt", port, "/x", str(tmp_path)) is tracker
    hold.set()
    browser_events.stop_download_tracking("b-evt")
    assert browser_events.get_download_tracker("b-evt") is None


def test_event_channel_marks_disconnected_on_error(ws_server, tmp_path):
    port = ws_server.getsockname()[1]
    threading.Thread(
        target=_serve_once, args=(ws_server, []), kwargs={"respond_error": True}, daemon=True
    ).start()
    tracker = browser_events.start_download_tracking(
        "b-err", port, "/devtools/browser/x", str(tmp_path)
    )
    assert tracker.connected is False
    assert "nope" in (tracker.error or "")


def test_event_channel_connect_refused(tmp_path):
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    tracker = browser_events.start_download_tracking(
        "b-refused", port, "/devtools/browser/x", str(tmp_path)
    )
    assert tracker.connected is False
    assert tracker.error
    browser_events.stop_all_tracking()


# ---------- R22：NetworkResponseTracker ----------


class TestNetworkResponseTracker:
    def test_record_document_response(self):
        from backend.tools.browser_events import NetworkResponseTracker

        t = NetworkResponseTracker()
        t.record("sess1", {"response": {"url": "https://x.com/", "status": 200, "type": "Document"}})
        rec = t.last_document("sess1")
        assert rec is not None
        assert rec["url"] == "https://x.com/"
        assert rec["status"] == 200

    def test_non_document_ignored(self):
        from backend.tools.browser_events import NetworkResponseTracker

        t = NetworkResponseTracker()
        t.record("s", {"response": {"url": "u", "status": 200, "type": "Script"}})
        assert t.last_document("s") is None

    def test_detach(self):
        from backend.tools.browser_events import NetworkResponseTracker

        t = NetworkResponseTracker()
        t.record("s", {"response": {"url": "u", "status": 200, "type": "Document"}})
        t.detach("s")
        assert t.last_document("s") is None


# ---------- R22 批次 2：attach + 事件状态查询链路 ----------


def _serve_with_network(server, response_events, hold=None, attach_error=False, seen=None):
    """握手 + setDownloadBehavior 后应答 attachToTarget / Network.enable，
    Network.enable 应答后下发 ``response_events``（带 sessionId 的事件帧）。

    ``seen`` 给定时记录收到的客户端 method（供断言"未发 setDownloadBehavior"）。"""
    conn, _ = server.accept()
    conn.settimeout(5)
    request = b""
    while b"\r\n\r\n" not in request:
        request += conn.recv(4096)
    key = next(
        line.split(":", 1)[1].strip()
        for line in request.decode("latin-1").split("\r\n")
        if line.lower().startswith("sec-websocket-key")
    )
    accept = base64.b64encode(hashlib.sha1((key + _WS_GUID).encode()).digest()).decode()
    conn.sendall(
        (
            "HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
            f"Connection: Upgrade\r\nSec-WebSocket-Accept: {accept}\r\n\r\n"
        ).encode()
    )
    # 不预读首帧：纯事件通道（R23）不发 setDownloadBehavior，首帧可能直接
    # 是 attachToTarget；统一在循环里按 method 应答。
    while True:
        try:
            client = json.loads(_ws_recv_client_text(conn))
        except (OSError, ValueError):
            break
        method = client.get("method")
        if seen is not None and method:
            seen.append(method)
        if method == "Browser.setDownloadBehavior":
            _ws_send_server_text(conn, json.dumps({"id": client["id"], "result": {}}))
        elif method == "Target.attachToTarget":
            if attach_error:
                _ws_send_server_text(
                    conn,
                    json.dumps({"id": client["id"], "error": {"message": "no target"}}),
                )
                continue
            _ws_send_server_text(
                conn,
                json.dumps({"id": client["id"], "result": {"sessionId": "net-sess-1"}}),
            )
        elif method == "Network.enable":
            _ws_send_server_text(conn, json.dumps({"id": client["id"], "result": {}}))
            for event in response_events:
                _ws_send_server_text(conn, json.dumps(event))
                time.sleep(0.02)
    if hold is not None:
        hold.wait(5)
    conn.close()


def test_ensure_attach_and_get_tracked_response(ws_server, tmp_path):
    port = ws_server.getsockname()[1]
    hold = threading.Event()
    events = [
        {
            "method": "Network.responseReceived",
            "sessionId": "net-sess-1",
            "params": {
                "response": {"url": "https://a.example/", "status": 302, "type": "Document"}
            },
        },
        {
            "method": "Network.responseReceived",
            "sessionId": "other-sess",
            "params": {"response": {"url": "https://b.example/", "status": 500, "type": "Document"}},
        },
    ]
    threading.Thread(
        target=_serve_with_network, args=(ws_server, events), kwargs={"hold": hold}, daemon=True
    ).start()
    tracker = browser_events.start_download_tracking(
        "b-net", port, "/devtools/browser/x", str(tmp_path)
    )
    assert tracker.connected is True

    session_id = browser_events.ensure_network_tracking("b-net", "t-1")
    assert session_id == "net-sess-1"
    # 幂等：同 target 复用既有 sessionId，不重复 attach
    assert browser_events.ensure_network_tracking("b-net", "t-1") == "net-sess-1"

    record = None
    other = None
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        record = browser_events.get_tracked_response("b-net", "net-sess-1")
        other = browser_events.get_tracked_response("b-net", "other-sess")
        if record and other:
            break
        time.sleep(0.05)
    assert record == {"url": "https://a.example/", "status": 302}
    # 其他 sessionId 的事件按其自身 id 记录，不污染本会话记录
    assert other == {"url": "https://b.example/", "status": 500}
    assert record == {"url": "https://a.example/", "status": 302}

    browser_events.detach_network_session("b-net", "net-sess-1")
    assert browser_events.get_tracked_response("b-net", "net-sess-1") is None
    hold.set()
    browser_events.stop_download_tracking("b-net")


def test_ensure_network_tracking_without_channel_is_noop():
    browser_events.stop_all_tracking()
    assert browser_events.ensure_network_tracking("b-missing", "t") is None
    assert browser_events.get_tracked_response("b-missing", "s") is None
    # 清理接口对未知会话同样不抛
    browser_events.detach_network_session("b-missing", "s")


def test_ensure_network_tracking_attach_error_returns_none(ws_server, tmp_path):
    port = ws_server.getsockname()[1]
    hold = threading.Event()
    threading.Thread(
        target=_serve_with_network,
        args=(ws_server, []),
        kwargs={"hold": hold, "attach_error": True},
        daemon=True,
    ).start()
    tracker = browser_events.start_download_tracking(
        "b-neterr", port, "/devtools/browser/x", str(tmp_path)
    )
    assert tracker.connected is True
    assert browser_events.ensure_network_tracking("b-neterr", "t-1") is None
    hold.set()
    browser_events.stop_download_tracking("b-neterr")


# ---------- R23：渲染池纯事件通道（跳过 setDownloadBehavior） ----------


def test_start_event_channel_skips_download_setup(ws_server):
    port = ws_server.getsockname()[1]
    hold = threading.Event()
    seen = []
    events = [
        {
            "method": "Network.responseReceived",
            "sessionId": "net-sess-1",
            "params": {
                "response": {"url": "https://r.example/", "status": 403, "type": "Document"}
            },
        }
    ]
    threading.Thread(
        target=_serve_with_network,
        args=(ws_server, events),
        kwargs={"hold": hold, "seen": seen},
        daemon=True,
    ).start()

    assert browser_events.start_event_channel("b-r23", port, "/devtools/browser/x") is True
    # 幂等：已连接复用，不新建连接
    assert browser_events.start_event_channel("b-r23", port, "/x") is True
    assert browser_events.ensure_network_tracking("b-r23", "t-1") == "net-sess-1"
    # 纯事件通道：从未发过下载行为命令，attach 正常
    assert "Browser.setDownloadBehavior" not in seen
    assert "Target.attachToTarget" in seen

    record = None
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        record = browser_events.get_tracked_response("b-r23", "net-sess-1")
        if record:
            break
        time.sleep(0.05)
    assert record == {"url": "https://r.example/", "status": 403}
    hold.set()
    browser_events.stop_download_tracking("b-r23")


def test_start_event_channel_connect_refused():
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    assert browser_events.start_event_channel("b-r23-refused", port, "/x") is False
    browser_events.stop_all_tracking()


def test_start_event_channel_stops_disconnected_channel(monkeypatch):
    """R29：替换断连旧通道前先 stop 其读线程，防 socket 半开滞留。"""
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()

    tracker = browser_events.DownloadTracker("")
    channel = browser_events._EventChannel(port, "/x", tracker)
    channel.tracker.connected = False  # 模拟半开断连
    stops: List[int] = []
    monkeypatch.setattr(channel, "stop", lambda: stops.append(1))
    browser_events._channels["b-dup"] = channel

    ok = browser_events.start_event_channel("b-dup", port, "/x")  # 连接拒绝也仅返回 False
    assert ok is False
    assert stops == [1]  # 旧通道被 stop 后才替换
    browser_events.stop_all_tracking()


# ---------- R33：Page.loadEventFired 就绪信号 ----------


class _FakeChannelServer:
    """在 _serve_with_network 基础上应答 Page.enable。"""

    pass


def test_arm_and_wait_page_load_signal(ws_server, tmp_path):
    """布防 → 服务器发 loadEventFired → wait 返回 True；detach 后清理。"""
    port = ws_server.getsockname()[1]
    hold = threading.Event()

    def _serve(server, hold):
        conn, _ = server.accept()
        conn.settimeout(5)
        request = b""
        while b"\r\n\r\n" not in request:
            request += conn.recv(4096)
        key = next(
            line.split(":", 1)[1].strip()
            for line in request.decode("latin-1").split("\r\n")
            if line.lower().startswith("sec-websocket-key")
        )
        accept = base64.b64encode(hashlib.sha1((key + _WS_GUID).encode()).digest()).decode()
        conn.sendall(
            (
                "HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
                f"Connection: Upgrade\r\nSec-WebSocket-Accept: {accept}\r\n\r\n"
            ).encode()
        )
        while True:
            try:
                client = json.loads(_ws_recv_client_text(conn))
            except (OSError, ValueError):
                break
            method = client.get("method")
            if method == "Browser.setDownloadBehavior":
                _ws_send_server_text(conn, json.dumps({"id": client["id"], "result": {}}))
            elif method in ("Target.attachToTarget", "Network.enable", "Page.enable"):
                _ws_send_server_text(
                    conn,
                    json.dumps(
                        {"id": client["id"], "result": {"sessionId": "pl-sess"}}
                    )
                    if method == "Target.attachToTarget"
                    else json.dumps({"id": client["id"], "result": {}}),
                )
            if method == "Page.enable":
                time.sleep(0.1)
                _ws_send_server_text(
                    conn,
                    json.dumps(
                        {
                            "method": "Page.loadEventFired",
                            "sessionId": "pl-sess",
                            "params": {},
                        }
                    ),
                )
        conn.close()

    threading.Thread(target=_serve, args=(ws_server, hold), daemon=True).start()
    tracker = browser_events.start_download_tracking(
        "b-pgload", port, "/devtools/browser/x", str(tmp_path)
    )
    assert tracker.connected is True

    session_id = browser_events.ensure_network_tracking("b-pgload", "t-1")
    assert session_id == "pl-sess"
    browser_events.arm_page_load("b-pgload", session_id)
    assert browser_events.wait_page_load("b-pgload", session_id, 5.0) is True
    # wait 后布防已消费；再次 wait 无信号 → False（不悬挂）
    assert browser_events.wait_page_load("b-pgload", session_id, 0.2) is False
    browser_events.detach_network_session("b-pgload", session_id)
    hold.set()
    browser_events.stop_download_tracking("b-pgload")


def test_wait_page_load_without_arm_returns_false(ws_server, tmp_path):
    port = ws_server.getsockname()[1]
    hold = threading.Event()

    def _serve(server, hold):
        conn, _ = server.accept()
        conn.settimeout(5)
        request = b""
        while b"\r\n\r\n" not in request:
            request += conn.recv(4096)
        key = next(
            line.split(":", 1)[1].strip()
            for line in request.decode("latin-1").split("\r\n")
            if line.lower().startswith("sec-websocket-key")
        )
        accept = base64.b64encode(hashlib.sha1((key + _WS_GUID).encode()).digest()).decode()
        conn.sendall(
            (
                "HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
                f"Connection: Upgrade\r\nSec-WebSocket-Accept: {accept}\r\n\r\n"
            ).encode()
        )
        while True:
            try:
                client = json.loads(_ws_recv_client_text(conn))
            except (OSError, ValueError):
                break
            method = client.get("method")
            if method == "Browser.setDownloadBehavior":
                _ws_send_server_text(conn, json.dumps({"id": client["id"], "result": {}}))
            elif method == "Target.attachToTarget":
                _ws_send_server_text(
                    conn,
                    json.dumps({"id": client["id"], "result": {"sessionId": "pl-sess"}}),
                )
            elif client.get("method") in ("Network.enable", "Page.enable"):
                _ws_send_server_text(conn, json.dumps({"id": client["id"], "result": {}}))

    threading.Thread(target=_serve, args=(ws_server, hold), daemon=True).start()
    tracker = browser_events.start_download_tracking(
        "b-pgload2", port, "/devtools/browser/x", str(tmp_path)
    )
    assert tracker.connected is True
    session_id = browser_events.ensure_network_tracking("b-pgload2", "t-1")
    assert session_id == "pl-sess"
    # 未布防：不悬挂，立即 False
    assert browser_events.wait_page_load("b-pgload2", session_id, 0.2) is False
    hold.set()
    browser_events.stop_download_tracking("b-pgload2")
