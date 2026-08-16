"""脚本化 OpenAI 兼容 mock 服务器 (线程托管, 无新依赖)。

模式改编自 claw-code ``crates/mock-anthropic-service``: 场景检测取自
请求消息中的 ``PARITY_SCENARIO:<name>`` 前缀, 响应脚本按请求序号
依次消费 (耗尽后重复最后一条)。

场景定义为纯数据 (SCENARIOS dict): 每个场景是响应脚本列表, 每条脚本:

- ``{"type": "message", "content": ..., "tool_calls": [...], "usage": {...}}``
  → 普通 chat.completion 响应 (带 tool_calls 时 finish_reason=tool_calls)
- ``{"type": "stream", "chunks": [...], "usage": {...}}``
  → SSE 流式响应 (末尾 chunk 携带 usage, 随后 ``data: [DONE]``)
"""

from __future__ import annotations

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

SCENARIO_PREFIX = "PARITY_SCENARIO:"
DEFAULT_MODEL = "mock-model"

# ==================== 场景数据 ====================

SCENARIOS: Dict[str, List[Dict[str, Any]]] = {
    # (a) 普通对话回复
    "plain": [
        {
            "type": "message",
            "content": "Hello from the mock.",
            "model": DEFAULT_MODEL,
            "usage": {"prompt_tokens": 11, "completion_tokens": 5, "total_tokens": 16},
        },
    ],
    # (b) tool_call 往返: 第一次返回 tool_calls, 第二次 (喂回工具结果后) 给终答
    "tool_round_trip": [
        {
            "type": "message",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_parity_1",
                    "name": "calculator",
                    "arguments": '{"expression": "6*7"}',
                }
            ],
            "model": DEFAULT_MODEL,
            "usage": {"prompt_tokens": 20, "completion_tokens": 9, "total_tokens": 29},
        },
        {
            "type": "message",
            "content": "The answer is 42.",
            "model": DEFAULT_MODEL,
            "usage": {"prompt_tokens": 33, "completion_tokens": 6, "total_tokens": 39},
        },
    ],
    # (c) SSE 流式回复
    "stream": [
        {
            "type": "stream",
            "chunks": ["Hello", " from", " stream"],
            "model": DEFAULT_MODEL,
            "usage": {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10},
        },
    ],
}


def detect_scenario(body: Dict[str, Any]) -> Optional[str]:
    """从请求消息里找 ``PARITY_SCENARIO:<name>`` 前缀 → 场景名。"""
    for message in body.get("messages") or []:
        content = message.get("content")
        if isinstance(content, str) and content.startswith(SCENARIO_PREFIX):
            return content[len(SCENARIO_PREFIX) :].split()[0].strip()
    return None


def build_message_response(script: Dict[str, Any]) -> Dict[str, Any]:
    """脚本 → OpenAI chat.completion 响应体。"""
    message: Dict[str, Any] = {"role": "assistant", "content": script.get("content", "")}
    tool_calls = script.get("tool_calls")
    if tool_calls:
        message["tool_calls"] = [
            {
                "id": tc["id"],
                "type": "function",
                "function": {"name": tc["name"], "arguments": tc["arguments"]},
            }
            for tc in tool_calls
        ]
    body: Dict[str, Any] = {
        "id": "chatcmpl-parity",
        "object": "chat.completion",
        "created": 1700000000,
        "model": script.get("model", DEFAULT_MODEL),
        "choices": [
            {
                "index": 0,
                "message": message,
                "finish_reason": "tool_calls" if tool_calls else "stop",
            }
        ],
    }
    if script.get("usage"):
        body["usage"] = script["usage"]
    return body


class MockLLMHandler(BaseHTTPRequestHandler):
    """/v1/chat/completions 的最小实现 (普通 + SSE 流式)。"""

    def do_POST(self) -> None:  # noqa: N802 (http.server 约定)
        if self.path.rstrip("/") != "/v1/chat/completions":
            self._send_json(404, {"error": {"message": f"unknown path {self.path}"}})
            return

        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            body = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            self._send_json(400, {"error": {"message": "invalid JSON body"}})
            return

        state: MockLLMServer = self.server.mock_state  # type: ignore[attr-defined]
        state.record_request(body, dict(self.headers))

        scenario = detect_scenario(body)
        if scenario is None:
            self._send_json(400, {"error": {"message": "missing parity scenario marker"}})
            return
        script = state.next_response(scenario)
        if script is None:
            self._send_json(400, {"error": {"message": f"unknown scenario: {scenario}"}})
            return

        if body.get("stream") or script.get("type") == "stream":
            self._send_stream(script)
        else:
            self._send_json(200, build_message_response(script))

    def _send_json(self, status: int, payload: Dict[str, Any]) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_stream(self, script: Dict[str, Any]) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        model = script.get("model", DEFAULT_MODEL)
        for chunk_text in script.get("chunks", []):
            payload = {
                "id": "chatcmpl-parity-stream",
                "object": "chat.completion.chunk",
                "created": 1700000000,
                "model": model,
                "choices": [
                    {"index": 0, "delta": {"content": chunk_text}, "finish_reason": None}
                ],
            }
            self.wfile.write(f"data: {json.dumps(payload)}\n\n".encode())
            self.wfile.flush()
        final = {
            "id": "chatcmpl-parity-stream",
            "object": "chat.completion.chunk",
            "created": 1700000000,
            "model": model,
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        }
        if script.get("usage"):
            final["usage"] = script["usage"]
        self.wfile.write(f"data: {json.dumps(final)}\n\n".encode())
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        logger.debug("mock-llm: " + format, *args)


class MockLLMServer:
    """线程托管的 mock OpenAI 服务器 (上下文管理器)。

    用法::

        with MockLLMServer(SCENARIOS) as server:
            client = LLMClient(LLMConfig(base_url=server.base_url, use_proxy=False, ...))
    """

    def __init__(self, scenarios: Dict[str, List[Dict[str, Any]]]) -> None:
        self._scenarios = scenarios
        self._httpd: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._call_counts: Dict[str, int] = {}
        self.requests: List[Dict[str, Any]] = []

    # ---------- 生命周期 ----------

    @property
    def base_url(self) -> str:
        assert self._httpd is not None, "server not started"
        return f"http://127.0.0.1:{self._httpd.server_address[1]}"

    def start(self) -> None:
        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), MockLLMHandler)
        self._httpd.mock_state = self  # type: ignore[attr-defined]
        self._thread = threading.Thread(
            target=self._httpd.serve_forever, daemon=True, name="mock-llm-server"
        )
        self._thread.start()

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def __enter__(self) -> MockLLMServer:
        self.start()
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.stop()

    # ---------- 场景分发 ----------

    def next_response(self, scenario: str) -> Optional[Dict[str, Any]]:
        scripts = self._scenarios.get(scenario)
        if not scripts:
            return None
        with self._lock:
            index = self._call_counts.get(scenario, 0)
            self._call_counts[scenario] = index + 1
        return scripts[min(index, len(scripts) - 1)]

    def call_count(self, scenario: str) -> int:
        with self._lock:
            return self._call_counts.get(scenario, 0)

    def record_request(self, body: Dict[str, Any], headers: Dict[str, str]) -> None:
        with self._lock:
            self.requests.append({"body": body, "headers": headers})
