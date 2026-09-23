# ruff: noqa: UP006, UP007, UP035, UP038, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""浏览器事件订阅（Round 5 §2.2 SN3：下载跟踪）。

``browser_cdp`` 的命令通道是"一次调用一条短连接、丢弃事件帧"，结构上收不到
``Browser.downloadWillBegin`` / ``Browser.downloadProgress``。本模块给每个
浏览器会话补一条**常驻** WS（守护线程），只做两件事：

1. 启动时 ``Browser.setDownloadBehavior{behavior:"allow", downloadPath, eventsEnabled:true}``
   把下载事件打开（下载目录与 browser_launch 保持一致）；
2. 循环读帧，把下载事件落到 ``DownloadTracker``（线程安全），供
   ``browser_downloads`` 工具列出 / 等待完成并返回最终路径。

失败面：连接断 / 浏览器退出 → 线程静默退出并把状态标为 ``disconnected``，
命令通道不受影响；``browser_downloads`` 会明示"事件通道未建立"。

py3.8 纪律：stdlib only；``browser_ws`` 复用。
"""

from __future__ import annotations

import json
import logging
import queue
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .browser_ws import WebSocketError, ws_close, ws_connect, ws_recv_text, ws_send_text

logger = logging.getLogger(__name__)

#: 事件通道建立超时（握手 + setDownloadBehavior 应答）
EVENTS_CONNECT_TIMEOUT = 10.0
#: 单会话保留的下载记录上限（超出丢最旧的已完成项）
MAX_DOWNLOAD_RECORDS = 200
#: ``wait_for_complete`` 默认 / 上限
DEFAULT_WAIT_TIMEOUT = 60.0
MAX_WAIT_TIMEOUT = 600.0
_POLL_INTERVAL = 0.2


class DownloadTracker:
    """单浏览器会话的下载状态表（线程安全）。"""

    def __init__(self, download_dir: str) -> None:
        self.download_dir = download_dir
        self._lock = threading.Lock()
        self._records: Dict[str, Dict[str, Any]] = {}
        self._order: List[str] = []
        self.connected = False
        self.error: Optional[str] = None
        self._event = threading.Event()

    # -- ingest ----------------------------------------------------------

    def handle_event(self, method: str, params: Dict[str, Any]) -> None:
        if method == "Browser.downloadWillBegin":
            guid = str(params.get("guid") or "")
            if not guid:
                return
            with self._lock:
                record = self._records.get(guid) or {"guid": guid, "state": "inProgress"}
                record.update(
                    {
                        "url": params.get("url"),
                        "suggested_filename": params.get("suggestedFilename"),
                        "frame_id": params.get("frameId"),
                        "started_at": int(time.time() * 1000),
                        "received_bytes": record.get("received_bytes", 0),
                        "total_bytes": record.get("total_bytes"),
                    }
                )
                self._put(guid, record)
        elif method == "Browser.downloadProgress":
            guid = str(params.get("guid") or "")
            if not guid:
                return
            with self._lock:
                record = self._records.get(guid) or {"guid": guid}
                state = str(params.get("state") or "inProgress")
                record["state"] = state
                record["received_bytes"] = int(params.get("receivedBytes") or 0)
                total = params.get("totalBytes")
                record["total_bytes"] = (
                    int(total) if isinstance(total, (int, float)) and total > 0 else None
                )
                if state in ("completed", "canceled"):
                    record["finished_at"] = int(time.time() * 1000)
                    if state == "completed":
                        record["path"] = self._resolve_path(record)
                self._put(guid, record)
            self._event.set()

    def _put(self, guid: str, record: Dict[str, Any]) -> None:
        if guid not in self._records:
            self._order.append(guid)
        self._records[guid] = record
        while len(self._order) > MAX_DOWNLOAD_RECORDS:
            oldest = self._order[0]
            if self._records.get(oldest, {}).get("state") == "inProgress":
                break
            self._order.pop(0)
            self._records.pop(oldest, None)

    def _resolve_path(self, record: Dict[str, Any]) -> Optional[str]:
        """完成后落盘路径：优先 ``downloadPath/guid``（Chrome ≥ 105 默认按 guid 命名），
        回退 ``suggestedFilename``（旧版 / 某些平台）。"""
        guid = str(record.get("guid") or "")
        name = str(record.get("suggested_filename") or "")
        base = Path(self.download_dir)
        for candidate in (base / guid if guid else None, base / name if name else None):
            if candidate is not None and candidate.is_file():
                return str(candidate)
        return None

    def resolve_completed_path(self, guid: str) -> Optional[str]:
        """已完成记录的落盘路径（事件到达时文件可能还没改名，查询时再补）。"""
        with self._lock:
            record = self._records.get(guid)
            if not record or record.get("state") != "completed":
                return None
            if not record.get("path"):
                record["path"] = self._resolve_path(record)
            return record.get("path")

    def mark_artifact_recorded(self, guid: str) -> bool:
        """首次标记返回 True（调用方据此只登记一次 artifact）。"""
        with self._lock:
            record = self._records.get(guid)
            if not record or record.get("artifact_recorded"):
                return False
            record["artifact_recorded"] = True
            return True

    # -- query -----------------------------------------------------------

    def snapshot(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [dict(self._records[g]) for g in self._order]

    def pending(self) -> List[Dict[str, Any]]:
        return [r for r in self.snapshot() if r.get("state") == "inProgress"]

    def wait_for_complete(self, timeout: float) -> bool:
        """阻塞直到没有 inProgress 记录或超时；返回是否全部结束。"""
        deadline = time.monotonic() + max(0.0, timeout)
        while True:
            if not self.pending():
                return True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            self._event.wait(min(_POLL_INTERVAL, remaining))
            self._event.clear()

    def mark_disconnected(self, error: str) -> None:
        self.connected = False
        self.error = error
        self._event.set()


class NetworkResponseTracker:
    """按 sessionId 记录最近一次主文档（type==Document）HTTP 响应（线程安全）。

    render_page 在 createTarget 后 attach + Network.enable，导航完成后经
    ``last_document(session_id)`` 取事件驱动的状态码。
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_session: Dict[str, Dict[str, Any]] = {}

    def record(self, session_id: str, params: Dict[str, Any]) -> None:
        response = params.get("response") or {}
        if str(response.get("type") or "") != "Document":
            return
        with self._lock:
            self._by_session[session_id] = {
                "url": str(response.get("url") or ""),
                "status": int(response.get("status") or 0),
            }

    def last_document(self, session_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            rec = self._by_session.get(session_id)
            return dict(rec) if rec else None

    def detach(self, session_id: str) -> None:
        with self._lock:
            self._by_session.pop(session_id, None)


class _EventChannel:
    """常驻 WS 线程：建立 → 开启下载事件 → 循环分发到 tracker。"""

    def __init__(self, port: int, ws_path: str, tracker: DownloadTracker) -> None:
        self._port = port
        self._ws_path = ws_path
        self.tracker = tracker
        self.network_tracker: Optional[NetworkResponseTracker] = None
        self._network_sessions: Dict[str, str] = {}  # session_id -> target_id
        self._sock: Any = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._msg_id = 0
        self._id_lock = threading.Lock()
        self._pending_lock = threading.Lock()
        self._pending: Dict[int, queue.Queue] = {}  # 应答 id -> 等待队列

    def _next_id(self) -> int:
        with self._id_lock:
            self._msg_id += 1
            return self._msg_id

    def _call(
        self,
        method: str,
        params: Dict[str, Any],
        session_id: str = "",
        timeout: float = 5.0,
    ) -> Optional[Dict[str, Any]]:
        """在常驻 WS 上发命令并同步等应答（应答帧经 _dispatch 路由回来）。

        不直接 recv —— 常驻读线程是唯一的帧读者，避免双读者抢帧；应答帧带
        命令 id 到达时投递到对应等待队列。出错 / 超时返回 None（尽力而为
        语义，由调用方决定降级路径）。
        """
        sock = self._sock
        if sock is None:
            return None
        msg_id = self._next_id()
        waiter: queue.Queue = queue.Queue()
        with self._pending_lock:
            self._pending[msg_id] = waiter
        try:
            frame: Dict[str, Any] = {"id": msg_id, "method": method, "params": params}
            if session_id:
                frame["sessionId"] = session_id
            ws_send_text(sock, json.dumps(frame))
            deadline = time.monotonic() + max(0.1, timeout)
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                try:
                    data = waiter.get(timeout=remaining)
                except queue.Empty:
                    return None
                if "error" in data:
                    return None
                return data
        except (OSError, WebSocketError):
            return None
        finally:
            with self._pending_lock:
                self._pending.pop(msg_id, None)

    def _wake_pending(self, message: str) -> None:
        """通道断开时唤醒所有在等应答的调用方（拿到 error 帧 → 返回 None）。"""
        with self._pending_lock:
            waiters = list(self._pending.values())
        for waiter in waiters:
            waiter.put({"error": {"message": message}})

    def start(self, setup_download: bool = True) -> bool:
        try:
            self._sock = ws_connect(
                "127.0.0.1", self._port, self._ws_path, timeout=EVENTS_CONNECT_TIMEOUT
            )
            if setup_download:
                ws_send_text(
                    self._sock,
                    json.dumps(
                        {
                            "id": 1,
                            "method": "Browser.setDownloadBehavior",
                            "params": {
                                "behavior": "allow",
                                "downloadPath": self.tracker.download_dir,
                                "eventsEnabled": True,
                            },
                        }
                    ),
                )
                deadline = time.monotonic() + EVENTS_CONNECT_TIMEOUT
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise WebSocketError("setDownloadBehavior 应答超时")
                    self._sock.settimeout(remaining)
                    data = json.loads(ws_recv_text(self._sock))
                    if data.get("id") == 1:
                        if "error" in data:
                            raise WebSocketError(
                                str(data["error"].get("message", "unknown"))
                            )
                        break
                    self._dispatch(data)
        except (OSError, WebSocketError, ValueError) as exc:
            self.tracker.mark_disconnected(f"{type(exc).__name__}: {exc}")
            self._close_sock()
            return False
        self.tracker.connected = True
        self._thread = threading.Thread(target=self._loop, name="browser-events", daemon=True)
        self._thread.start()
        return True

    def _dispatch(self, data: Dict[str, Any]) -> None:
        # 应答帧（带 id）：路由到等待队列；无人等待（含 start() 握手期的
        # 迟到应答）则忽略。
        mid = data.get("id")
        if mid is not None:
            with self._pending_lock:
                waiter = self._pending.get(mid)
            if waiter is not None:
                waiter.put(data)
                return
        method = data.get("method")
        if isinstance(method, str) and method.startswith("Browser.download"):
            self.tracker.handle_event(method, data.get("params") or {})
        if method == "Network.responseReceived" and self.network_tracker is not None:
            session_id = str(data.get("sessionId") or "")
            if session_id:
                self.network_tracker.record(session_id, data.get("params") or {})

    def attach_network(self, target_id: str) -> Optional[str]:
        """attach 到指定 target + Network.enable；返回 sessionId 或 None。

        在常驻浏览器级 WS 上发送（flatten 模式）：应答帧由常驻读线程经
        ``_dispatch`` 路由回 ``_call``，不与读循环抢帧；后续 Network 事件带
        sessionId 到达并被 ``_dispatch`` 分发到 network_tracker。
        """
        resp = self._call("Target.attachToTarget", {"targetId": target_id, "flatten": True})
        if not resp:
            return None
        session_id = str((resp.get("result") or {}).get("sessionId") or "") or None
        if not session_id:
            return None
        self._network_sessions[session_id] = target_id
        self._call("Network.enable", {}, session_id=session_id)
        return session_id

    def _loop(self) -> None:
        sock = self._sock
        try:
            sock.settimeout(None)
            while not self._stop.is_set():
                data = json.loads(ws_recv_text(sock))
                self._dispatch(data)
        except (OSError, WebSocketError, ValueError) as exc:
            if not self._stop.is_set():
                self.tracker.mark_disconnected(f"{type(exc).__name__}: {exc}")
            self._wake_pending("channel closed")
        finally:
            self._close_sock()

    def _close_sock(self) -> None:
        sock, self._sock = self._sock, None
        if sock is not None:
            ws_close(sock)

    def stop(self) -> None:
        self._stop.set()
        self._close_sock()


_channels: Dict[str, _EventChannel] = {}
_channels_lock = threading.Lock()


def start_download_tracking(
    browser_id: str, port: int, ws_path: str, download_dir: str
) -> DownloadTracker:
    """为会话建立事件通道（幂等：已有则复用）；连接失败时 tracker.connected=False。"""
    with _channels_lock:
        existing = _channels.get(browser_id)
        if existing is not None and existing.tracker.connected:
            return existing.tracker
        tracker = DownloadTracker(download_dir)
        channel = _EventChannel(port, ws_path, tracker)
        _channels[browser_id] = channel
    channel.start()
    return tracker


def get_download_tracker(browser_id: str) -> Optional[DownloadTracker]:
    with _channels_lock:
        channel = _channels.get(browser_id)
    return channel.tracker if channel else None


def start_event_channel(browser_id: str, port: int, ws_path: str) -> bool:
    """为无下载需求的浏览器（渲染池）建立纯事件通道（R23）。

    跳过 ``setDownloadBehavior``——渲染池不落下载，通道只服务 Network 事件
    （R22 批次 2 的 render_page 事件状态由此在生产渲染路径生效）。幂等：
    已连接复用；失败静默（返回 False，调用方回退 Navigation Timing）。
    """
    with _channels_lock:
        existing = _channels.get(browser_id)
        if existing is not None and existing.tracker.connected:
            return True
        tracker = DownloadTracker("")  # 渲染池不落下载，目录留空
        channel = _EventChannel(port, ws_path, tracker)
        _channels[browser_id] = channel
    return channel.start(setup_download=False)


# ---------- R22 批次 2：渲染分支 Network 事件化接口 ----------


def ensure_network_tracking(browser_id: str, target_id: str) -> Optional[str]:
    """render_page 用：确保事件通道 attach 到渲染标签页并开启 Network 事件。

    幂等（同 target 复用既有 sessionId）；通道未建立 / attach 失败返回
    None —— 调用方回退 Navigation Timing 读状态，不影响渲染主流程。
    """
    with _channels_lock:
        channel = _channels.get(browser_id)
        if channel is None:
            return None
        if channel.network_tracker is None:
            channel.network_tracker = NetworkResponseTracker()
        for session_id, tid in channel._network_sessions.items():
            if tid == target_id:
                return session_id
    return channel.attach_network(target_id)


def get_tracked_response(browser_id: str, session_id: str) -> Optional[Dict[str, Any]]:
    """取该渲染会话最近一次主文档响应（事件驱动，含 302 中间 hop 状态）。"""
    with _channels_lock:
        channel = _channels.get(browser_id)
    if channel is None or channel.network_tracker is None:
        return None
    return channel.network_tracker.last_document(session_id)


def detach_network_session(browser_id: str, session_id: str) -> None:
    """渲染结束清理：丢掉该 sessionId 的 target 映射与响应记录（尽力而为）。"""
    with _channels_lock:
        channel = _channels.get(browser_id)
    if channel is None:
        return
    channel._network_sessions.pop(session_id, None)
    if channel.network_tracker is not None:
        channel.network_tracker.detach(session_id)


def stop_download_tracking(browser_id: str) -> None:
    with _channels_lock:
        channel = _channels.pop(browser_id, None)
    if channel is not None:
        channel.stop()


def stop_all_tracking() -> None:
    with _channels_lock:
        channels = list(_channels.values())
        _channels.clear()
    for channel in channels:
        channel.stop()


def list_download_dir(download_dir: str) -> List[Dict[str, Any]]:
    """兜底：事件通道不可用时直接列下载目录（含 Chrome 的 ``.crdownload`` 半成品）。"""
    base = Path(download_dir)
    if not base.is_dir():
        return []
    items: List[Dict[str, Any]] = []
    for entry in sorted(
        base.iterdir(), key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True
    ):
        if not entry.is_file():
            continue
        try:
            stat = entry.stat()
        except OSError:
            continue
        items.append(
            {
                "path": str(entry),
                "name": entry.name,
                "bytes": stat.st_size,
                "modified_at": int(stat.st_mtime * 1000),
                "state": "inProgress" if entry.name.endswith(".crdownload") else "completed",
            }
        )
    return items[:MAX_DOWNLOAD_RECORDS]


__all__ = [
    "DEFAULT_WAIT_TIMEOUT",
    "MAX_WAIT_TIMEOUT",
    "NetworkResponseTracker",
    "DownloadTracker",
    "detach_network_session",
    "ensure_network_tracking",
    "get_download_tracker",
    "get_tracked_response",
    "list_download_dir",
    "start_download_tracking",
    "start_event_channel",
    "stop_all_tracking",
    "stop_download_tracking",
]
