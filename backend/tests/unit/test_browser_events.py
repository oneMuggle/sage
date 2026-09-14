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
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and not tracker.snapshot():
        time.sleep(0.05)
    record = tracker.snapshot()[0]
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
